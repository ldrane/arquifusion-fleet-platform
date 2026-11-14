"""Funciones de lectura que el asistente puede invocar por function calling (RF-14).

Solo lecturas acotadas sobre DynamoDB (nunca SQL libre). Las tablas siguen la convención de contratos.md §9.
`zone_scope` restringe los resultados a la zona del usuario cuando su rol no es global (RNF-08).
"""

from decimal import Decimal

from boto3.dynamodb.conditions import Attr, Key

AT_RISK_HEALTH = 50
MAX_ROWS = 20
CLOSED_STATUSES = ("resolved", "closed")
INSIGHT_KINDS = (
    "maintenance_plan",
    "parts_ranking",
    "parts_forecast#30",
    "fuel#7d",
    "productivity#7d",
    "kpis#7d",
    "report#daily",
    "ml_model",
)

FUNCTION_DECLARATIONS: list[dict] = [
    {
        "name": "get_machines_at_risk",
        "description": "Lista las máquinas con health score bajo o que requieren intervención, de peor a mejor.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"zone": {"type": "STRING", "description": "Zona, por ejemplo norte"}},
        },
    },
    {
        "name": "get_machine_detail",
        "description": "Estado, health score, severidad, factores principales y mantenimiento de una máquina.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"machine_id": {"type": "STRING", "description": "ID de la máquina, por ejemplo EX-023"}},
            "required": ["machine_id"],
        },
    },
    {
        "name": "get_open_incidents",
        "description": "Incidentes abiertos (no resueltos ni cerrados), opcionalmente por zona.",
        "parameters": {"type": "OBJECT", "properties": {"zone": {"type": "STRING"}}},
    },
    {
        "name": "get_insight",
        "description": (
            "Último análisis diario: plan de mantenimiento, ranking o pronóstico de repuestos, combustible, "
            "productividad, KPIs, reporte gerencial o métricas del modelo."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {"kind": {"type": "STRING", "enum": list(INSIGHT_KINDS)}},
            "required": ["kind"],
        },
    },
]


def plain(value):
    """Convierte los Decimal de DynamoDB a int/float para serializar a JSON."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    return value


def _scan(table, **kwargs) -> list[dict]:
    items, start = [], None
    while True:
        page = table.scan(**kwargs, **({"ExclusiveStartKey": start} if start else {}))
        items.extend(page.get("Items", []))
        start = page.get("LastEvaluatedKey")
        if not start:
            return [plain(i) for i in items]


def _zone_of(item: dict) -> str | None:
    return item.get("zone") or (item.get("location") or {}).get("zone")


class ToolBox:
    """Ejecuta las funciones declaradas en FUNCTION_DECLARATIONS."""

    def __init__(self, machines_table, incidents_table, insights_table, zone_scope: str | None = None):
        self._machines = machines_table
        self._incidents = incidents_table
        self._insights = insights_table
        self._zone_scope = zone_scope

    def call(self, name: str, args: dict) -> dict:
        handlers = {
            "get_machines_at_risk": self.get_machines_at_risk,
            "get_machine_detail": self.get_machine_detail,
            "get_open_incidents": self.get_open_incidents,
            "get_insight": self.get_insight,
        }
        if name not in handlers:
            return {"error": f"función desconocida: {name}"}
        return handlers[name](**{k: v for k, v in (args or {}).items() if isinstance(v, str)})

    def _zone(self, requested: str | None) -> str | None:
        return self._zone_scope or (requested.lower() if requested else None)

    def get_machines_at_risk(self, zone: str | None = None) -> dict:
        zone = self._zone(zone)
        machines = _scan(self._machines, FilterExpression=Attr("machine_id").exists())
        at_risk = [
            m
            for m in machines
            if (m.get("health_score", 100) < AT_RISK_HEALTH or m.get("status") == "needs_intervention")
            and (zone is None or _zone_of(m) == zone)
        ]
        at_risk.sort(key=lambda m: m.get("health_score", 100))
        fields = ("machine_id", "type", "status", "severity", "health_score")
        return {
            "zone": zone,
            "total": len(at_risk),
            "machines": [{**{k: m.get(k) for k in fields}, "zone": _zone_of(m)} for m in at_risk[:MAX_ROWS]],
        }

    def get_machine_detail(self, machine_id: str) -> dict:
        found = _scan(self._machines, FilterExpression=Attr("machine_id").eq(machine_id.upper()))
        if not found:
            return {"error": f"No existe la máquina {machine_id}"}
        machine = found[0]
        if self._zone_scope and _zone_of(machine) != self._zone_scope:
            return {"error": f"La máquina {machine_id} no pertenece a tu zona"}
        fields = (
            "machine_id",
            "model",
            "type",
            "status",
            "severity",
            "health_score",
            "top_factors",
            "operating_hours",
            "last_maintenance_at",
            "next_maintenance_at",
            "open_incident_id",
        )
        return {**{k: machine.get(k) for k in fields if k in machine}, "zone": _zone_of(machine)}

    def get_open_incidents(self, zone: str | None = None) -> dict:
        zone = self._zone(zone)
        condition = Attr("status").exists() & ~Attr("status").is_in(list(CLOSED_STATUSES))
        if zone:
            condition &= Attr("zone").eq(zone)
        incidents = _scan(self._incidents, FilterExpression=condition)
        fields = ("incident_id", "machine_ids", "zone", "severity", "status", "assigned_technician_id", "detected_at")
        incidents.sort(key=lambda i: i.get("detected_at", ""), reverse=True)
        return {
            "zone": zone,
            "total": len(incidents),
            "incidents": [{k: i.get(k) for k in fields} for i in incidents[:MAX_ROWS]],
        }

    def get_insight(self, kind: str) -> dict:
        if kind not in INSIGHT_KINDS:
            return {"error": f"Tipo de análisis no disponible: {kind}"}
        page = self._insights.query(KeyConditionExpression=Key("pk").eq(kind) & Key("sk").eq("LATEST"))
        items = page.get("Items", [])
        if not items:
            return {"error": "Aún no hay análisis de este tipo"}
        item = plain(items[0])
        data = item.get("data")
        if self._zone_scope and isinstance(data, list):
            data = [row for row in data if not isinstance(row, dict) or row.get("zone") in (None, self._zone_scope)]
        if isinstance(data, list):
            data = data[:MAX_ROWS]
        return {"kind": kind, "generated_at": item.get("generated_at"), "data": data}
