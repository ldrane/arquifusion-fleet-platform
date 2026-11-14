"""Datos maestros de ArquiFusion (C1). Generación 100% determinista.

Funciones puras, sin AWS: el mismo código produce siempre los mismos datos.
Los consume:
  - scripts/seed.py            -> carga en DynamoDB
  - contracts/fixtures/seed/   -> JSON para el simulador (A) y la SFN (B)

IDs según contratos.md §1: EX-023, TEC-07, WH-01, CMP-014.
Si cambias algo aquí, sube SEED_VERSION y vuelve a exportar los fixtures.
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

SEED_VERSION = 2  # v2: WH-04 oeste, expected_interval_s=60, reglas alineadas a contratos.md §10
RANDOM_SEED = 27  # Grupo 27
REFERENCE_DATE = date(2026, 11, 14)  # fechas relativas a este día (no a "hoy") para que sea determinista
OPERATION_ID = "OP-01"
# El simulador envía cada 60 s (simulator/cli.py); heartbeat declara silencio a 3x = 180 s (contratos.md §3).
EXPECTED_INTERVAL_S = 60

# --------------------------------------------------------------------------- zonas
# Operación minera ficticia en la sierra central. Cada zona es un círculo de ~1.5 km.
OPERATION_CENTER = (-11.9500, -76.4000)
ZONES = {
    "norte": {"center": (-11.9200, -76.4000), "radius_deg": 0.012},
    "sur": {"center": (-11.9800, -76.4000), "radius_deg": 0.012},
    "este": {"center": (-11.9500, -76.3650), "radius_deg": 0.012},
    "oeste": {"center": (-11.9500, -76.4350), "radius_deg": 0.012},
}

WAREHOUSES = [
    {
        "warehouse_id": "WH-01",
        "name": "Almacén Norte",
        "zone": "norte",
        "location": {"lat": -11.9150, "lon": -76.3950, "zone": "norte"},
    },
    {
        "warehouse_id": "WH-02",
        "name": "Almacén Sur",
        "zone": "sur",
        "location": {"lat": -11.9850, "lon": -76.4050, "zone": "sur"},
    },
    {
        "warehouse_id": "WH-03",
        "name": "Almacén Este",
        "zone": "este",
        "location": {"lat": -11.9480, "lon": -76.3600, "zone": "este"},
    },
    {
        "warehouse_id": "WH-04",
        "name": "Almacén Oeste",
        "zone": "oeste",
        "location": {"lat": -11.9480, "lon": -76.4400, "zone": "oeste"},
    },
]

# --------------------------------------------------------------------------- modelos
# nominal = [media, desviación] de operación normal. Lo usa el simulador (A) como baseline.
MACHINE_MODELS = [
    {
        "model_id": "CAT-336",
        "brand": "Caterpillar",
        "type": "excavator",
        "payload_t": 2.5,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [88, 3],
            "vibration_mm_s": [4.0, 0.6],
            "pressure_bar": [300, 15],
            "fuel_rate_lph": [38, 4],
            "load_pct": [70, 10],
            "speed_kmh": [3, 1.5],
            "rpm": [1800, 80],
        },
    },
    {
        "model_id": "KOM-PC2000",
        "brand": "Komatsu",
        "type": "excavator",
        "payload_t": 12.0,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [90, 3],
            "vibration_mm_s": [4.5, 0.6],
            "pressure_bar": [320, 15],
            "fuel_rate_lph": [110, 8],
            "load_pct": [72, 10],
            "speed_kmh": [2.5, 1.2],
            "rpm": [1800, 80],
        },
    },
    {
        "model_id": "CAT-793F",
        "brand": "Caterpillar",
        "type": "mining_truck",
        "payload_t": 227.0,
        "maintenance_interval_h": 500,
        "nominal": {
            "temperature_c": [92, 3],
            "vibration_mm_s": [3.5, 0.5],
            "pressure_bar": [180, 10],
            "fuel_rate_lph": [170, 12],
            "load_pct": [75, 15],
            "speed_kmh": [30, 8],
            "rpm": [1700, 90],
        },
    },
    {
        "model_id": "KOM-930E",
        "brand": "Komatsu",
        "type": "mining_truck",
        "payload_t": 290.0,
        "maintenance_interval_h": 500,
        "nominal": {
            "temperature_c": [93, 3],
            "vibration_mm_s": [3.6, 0.5],
            "pressure_bar": [185, 10],
            "fuel_rate_lph": [190, 14],
            "load_pct": [75, 15],
            "speed_kmh": [28, 8],
            "rpm": [1750, 90],
        },
    },
    {
        "model_id": "CAT-994K",
        "brand": "Caterpillar",
        "type": "loader",
        "payload_t": 40.0,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [90, 3],
            "vibration_mm_s": [4.2, 0.6],
            "pressure_bar": [280, 15],
            "fuel_rate_lph": [160, 10],
            "load_pct": [70, 12],
            "speed_kmh": [10, 4],
            "rpm": [1850, 80],
        },
    },
    {
        "model_id": "KOM-WA900",
        "brand": "Komatsu",
        "type": "loader",
        "payload_t": 23.0,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [89, 3],
            "vibration_mm_s": [4.1, 0.6],
            "pressure_bar": [270, 15],
            "fuel_rate_lph": [120, 9],
            "load_pct": [70, 12],
            "speed_kmh": [10, 4],
            "rpm": [1800, 80],
        },
    },
    {
        "model_id": "CAT-D10T",
        "brand": "Caterpillar",
        "type": "bulldozer",
        "payload_t": 0.0,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [91, 3],
            "vibration_mm_s": [5.0, 0.7],
            "pressure_bar": [250, 12],
            "fuel_rate_lph": [70, 6],
            "load_pct": [68, 12],
            "speed_kmh": [6, 2],
            "rpm": [1900, 80],
        },
    },
    {
        "model_id": "KOM-D375A",
        "brand": "Komatsu",
        "type": "bulldozer",
        "payload_t": 0.0,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [91, 3],
            "vibration_mm_s": [5.2, 0.7],
            "pressure_bar": [255, 12],
            "fuel_rate_lph": [75, 6],
            "load_pct": [68, 12],
            "speed_kmh": [6, 2],
            "rpm": [1900, 80],
        },
    },
    {
        "model_id": "EPI-PV271",
        "brand": "Epiroc",
        "type": "drill",
        "payload_t": 0.0,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [87, 3],
            "vibration_mm_s": [6.0, 0.8],
            "pressure_bar": [350, 20],
            "fuel_rate_lph": [90, 7],
            "load_pct": [65, 12],
            "speed_kmh": [1.5, 0.8],
            "rpm": [1800, 70],
        },
    },
    {
        "model_id": "SAN-DR412i",
        "brand": "Sandvik",
        "type": "drill",
        "payload_t": 0.0,
        "maintenance_interval_h": 250,
        "nominal": {
            "temperature_c": [86, 3],
            "vibration_mm_s": [5.8, 0.8],
            "pressure_bar": [340, 20],
            "fuel_rate_lph": [85, 7],
            "load_pct": [65, 12],
            "speed_kmh": [1.5, 0.8],
            "rpm": [1800, 70],
        },
    },
]

# prefijo de ID (patrón ^[A-Z]{2}-[0-9]{3,4}$ del OpenAPI), cantidad y modelos por tipo
FLEET_PLAN = [
    {"type": "excavator", "prefix": "EX", "count": 25, "models": ["CAT-336", "KOM-PC2000"]},
    {"type": "mining_truck", "prefix": "CM", "count": 35, "models": ["CAT-793F", "KOM-930E"]},
    {"type": "loader", "prefix": "CF", "count": 15, "models": ["CAT-994K", "KOM-WA900"]},
    {"type": "bulldozer", "prefix": "BD", "count": 12, "models": ["CAT-D10T", "KOM-D375A"]},
    {"type": "drill", "prefix": "PF", "count": 13, "models": ["EPI-PV271", "SAN-DR412i"]},
]
ZONE_ORDER = ["norte", "sur", "este", "oeste"]

# Máquinas fijadas porque aparecen en contratos.md / openapi.yaml / fixtures del golden path
PINNED_MACHINES = {"EX-023": {"model": "CAT-336", "zone": "norte"}}

ALL_MODELS = [m["model_id"] for m in MACHINE_MODELS]


def _models_of(*types: str) -> list[str]:
    return [m["model_id"] for m in MACHINE_MODELS if m["type"] in types]


# --------------------------------------------------------------------------- catálogo
# specialty usa el enum del OpenAPI: motor | hidraulica | electrica | neumaticos
CATALOG = [
    ("CMP-001", "Filtro de aceite de motor", "motor", ALL_MODELS, 45, 2),
    ("CMP-002", "Filtro de combustible", "motor", ALL_MODELS, 38, 2),
    ("CMP-003", "Filtro de aire primario", "motor", ALL_MODELS, 120, 3),
    ("CMP-004", "Inyector de combustible", "motor", ALL_MODELS, 650, 7),
    ("CMP-005", "Turbocompresor", "motor", ALL_MODELS, 4800, 21),
    ("CMP-006", "Bomba de agua", "motor", ALL_MODELS, 1200, 10),
    ("CMP-007", "Radiador", "motor", ALL_MODELS, 6500, 30),
    ("CMP-008", "Correa de accesorios", "motor", ALL_MODELS, 85, 3),
    (
        "CMP-009",
        "Bomba hidráulica principal",
        "hidraulica",
        _models_of("excavator", "loader", "bulldozer", "drill"),
        18500,
        35,
    ),
    ("CMP-010", "Cilindro hidráulico de brazo", "hidraulica", _models_of("excavator"), 9200, 28),
    ("CMP-011", "Manguera hidráulica de alta presión", "hidraulica", ALL_MODELS, 260, 4),
    ("CMP-012", "Kit de sellos de cilindro hidráulico", "hidraulica", ALL_MODELS, 340, 5),
    (
        "CMP-013",
        "Válvula de control hidráulico",
        "hidraulica",
        _models_of("excavator", "loader", "bulldozer", "drill"),
        5400,
        20,
    ),
    ("CMP-014", "Kit de rodamientos de motor", "motor", ALL_MODELS, 1350, 10),
    ("CMP-015", "Alternador", "electrica", ALL_MODELS, 1900, 12),
    ("CMP-016", "Motor de arranque", "electrica", ALL_MODELS, 1600, 12),
    ("CMP-017", "Batería 12 V servicio pesado", "electrica", ALL_MODELS, 320, 3),
    ("CMP-018", "Sensor de temperatura de refrigerante", "electrica", ALL_MODELS, 140, 4),
    ("CMP-019", "Sensor de vibración (acelerómetro)", "electrica", ALL_MODELS, 480, 7),
    ("CMP-020", "Módulo de control electrónico (ECU)", "electrica", ALL_MODELS, 7800, 30),
    ("CMP-021", "Neumático OTR 59/80R63", "neumaticos", _models_of("mining_truck"), 42000, 45),
    ("CMP-022", "Neumático OTR 45/65R45", "neumaticos", _models_of("loader"), 18000, 40),
    ("CMP-023", "Zapata de oruga", "neumaticos", _models_of("excavator", "bulldozer", "drill"), 650, 14),
    ("CMP-024", "Broca tricónica 10 5/8 in", "hidraulica", _models_of("drill"), 2900, 15),
    ("CMP-025", "Kit de discos de freno", "hidraulica", _models_of("mining_truck", "loader"), 2100, 10),
]

# --------------------------------------------------------------------------- técnicos
# user_id = cognito:username del usuario demo (convención propuesta a B, ver docs/h0-persona-c.md)
TECHNICIANS = [
    ("TEC-01", "Ana Huamán", "norte", ["motor", "electrica"], "day"),
    ("TEC-02", "Luis Quispe", "sur", ["hidraulica", "motor"], "day"),
    ("TEC-03", "Rosa Condori", "este", ["electrica", "neumaticos"], "day"),
    ("TEC-04", "Carlos Mamani", "oeste", ["motor", "hidraulica"], "day"),
    ("TEC-05", "María Ccori", "norte", ["neumaticos", "hidraulica"], "night"),
    ("TEC-06", "Jorge Flores", "sur", ["electrica"], "night"),
    ("TEC-07", "Pedro Rojas", "norte", ["motor", "hidraulica"], "day"),
    ("TEC-08", "Lucía Vargas", "este", ["hidraulica", "motor"], "night"),
    ("TEC-09", "Miguel Chávez", "oeste", ["neumaticos", "electrica"], "night"),
    ("TEC-10", "Sofía Ramos", "sur", ["neumaticos", "motor"], "day"),
    ("TEC-11", "Diego Torres", "este", ["motor"], "day"),
    ("TEC-12", "Elena Paredes", "oeste", ["hidraulica", "electrica"], "day"),
]

# Ubicación inicial fijada para que el golden path sea determinista (contracts/fixtures/internal/scoring_*.json):
# para EX-023 (motor, high) gana TEC-07 (junto a WH-01) y el 2.º candidato es TEC-01 (rechazo -> reasignación).
PINNED_TECH_LOCATIONS = {
    "TEC-07": {"lat": -11.9150, "lon": -76.3965, "zone": "norte"},
    "TEC-01": {"lat": -11.9280, "lon": -76.4060, "zone": "norte"},
}

# --------------------------------------------------------------------------- notificaciones
# event_type = tabla "transición -> event_type" de contratos.md §10 (la usa notificar, B).
# Para event_type incident.*, la regla del rol `tecnico` notifica SOLO al técnico asignado (o al nuevo candidato).
# channels: push (FCM vía Pub/Sub), email (SNS alerts-{rol}),
# dashboard (sin envío: ya se ve por la réplica a Firestore).
# content_profile: technical (detalle) | operational (seguridad) | executive (impacto) -> lo usa notificar/ia-gemini
NOTIFICATION_RULES = [
    ("incident.detected", "operador", "high", ["push"], "operational", 10),
    ("incident.detected", "mantenimiento", "medium", ["email", "dashboard"], "technical", 15),
    ("incident.detected", "supervisor", "high", ["email", "dashboard"], "operational", 15),
    ("incident.detected", "gerencia", "critical", ["email"], "executive", 60),
    ("incident.assigned", "tecnico", "info", ["push", "email"], "technical", 0),
    ("incident.assigned", "mantenimiento", "medium", ["dashboard"], "technical", 0),
    ("incident.in_progress", "operador", "medium", ["push"], "operational", 0),
    ("incident.in_progress", "mantenimiento", "info", ["dashboard"], "technical", 0),
    ("incident.escalated", "tecnico", "info", ["push"], "technical", 5),
    ("incident.escalated", "mantenimiento", "low", ["email", "push"], "technical", 5),
    ("incident.escalated", "supervisor", "high", ["email"], "operational", 15),
    ("incident.resolved", "operador", "info", ["push"], "operational", 0),
    ("incident.resolved", "mantenimiento", "info", ["dashboard"], "technical", 0),
    ("incident.closed", "mantenimiento", "info", ["dashboard"], "technical", 0),
    ("incident.closed", "supervisor", "medium", ["dashboard"], "operational", 0),
    ("incident.closed", "gerencia", "critical", ["email"], "executive", 60),
    ("machine.silent", "mantenimiento", "low", ["dashboard", "email"], "technical", 30),
    ("machine.silent", "supervisor", "medium", ["dashboard"], "operational", 30),
    ("parts.shortage", "mantenimiento", "info", ["email"], "technical", 60),
    ("parts.shortage", "admin", "info", ["email"], "executive", 240),
    ("report.daily", "admin", "info", ["email"], "executive", 0),
    ("report.daily", "gerencia", "info", ["email"], "executive", 0),
]
NOTIFICATION_EVENT_TYPES = sorted({r[0] for r in NOTIFICATION_RULES})

# Ajustes de inventario para que la demo tenga alertas visibles: (warehouse, component) -> stock
INVENTORY_OVERRIDES = {
    ("WH-01", "CMP-014"): 2,  # justo en el mínimo: el golden path (EX-023, rodamiento) tiene stock
    ("WH-02", "CMP-021"): 0,  # low_stock: neumático de camión agotado en el sur
    ("WH-03", "CMP-005"): 0,  # low_stock: turbo agotado en el este
    ("WH-01", "CMP-008"): 60,  # overstock
    ("WH-03", "CMP-001"): 90,  # overstock
}


# =========================================================================== generadores
def _point_in_zone(rng: random.Random, zone: str) -> dict:
    cfg = ZONES[zone]
    angle = rng.uniform(0, 2 * math.pi)
    radius = cfg["radius_deg"] * math.sqrt(rng.random())
    lat = cfg["center"][0] + radius * math.sin(angle)
    lon = cfg["center"][1] + radius * math.cos(angle)
    return {"lat": round(lat, 6), "lon": round(lon, 6), "zone": zone}


def build_machine_models() -> list[dict]:
    comps_by_model: dict[str, list[str]] = {m: [] for m in ALL_MODELS}
    for comp_id, _name, _spec, models, _cost, _lead in CATALOG:
        for m in models:
            comps_by_model[m].append(comp_id)
    out = []
    for m in MACHINE_MODELS:
        item = dict(m)
        item["component_ids"] = comps_by_model[m["model_id"]]
        out.append(item)
    return out


def build_machines() -> list[dict]:
    rng = random.Random(RANDOM_SEED)
    machines = []
    for plan in FLEET_PLAN:
        for n in range(1, plan["count"] + 1):
            machine_id = f"{plan['prefix']}-{n:03d}"
            pinned = PINNED_MACHINES.get(machine_id, {})
            model = pinned.get("model") or plan["models"][(n - 1) % len(plan["models"])]
            zone = pinned.get("zone") or ZONE_ORDER[rng.randrange(len(ZONE_ORDER))]
            model_cfg = next(m for m in MACHINE_MODELS if m["model_id"] == model)
            interval = model_cfg["maintenance_interval_h"]
            days_since = rng.randint(3, 40)
            last_maint = REFERENCE_DATE - timedelta(days=days_since)
            # ~16 h de uso diario -> días hasta el próximo mantenimiento por horas
            next_maint = last_maint + timedelta(days=round(interval / 16))
            machines.append(
                {
                    "machine_id": machine_id,
                    "operation_id": OPERATION_ID,
                    "model": model,
                    "type": plan["type"],
                    "zone": zone,  # duplicado de location.zone para el GSI by_zone
                    "location": _point_in_zone(rng, zone),
                    "home_location": None,  # se completa abajo (igual a location inicial)
                    "status": "operational",
                    "severity": "info",
                    "health_score": rng.randint(84, 99),
                    "last_seen_at": None,  # aún no hay telemetría (heartbeat debe ignorar null)
                    "expected_interval_s": EXPECTED_INTERVAL_S,
                    "operating_hours": round(rng.uniform(1500, 18000), 1),
                    "last_maintenance_at": last_maint.isoformat(),
                    "next_maintenance_at": next_maint.isoformat(),
                    "failure_probability": None,
                    "rul_hours": None,
                    "open_incident_id": None,
                    "top_factors": [],
                    "model_version": None,
                    "seed_version": SEED_VERSION,
                }
            )
    for m in machines:
        m["home_location"] = dict(m["location"])
    return machines


def build_technicians() -> list[dict]:
    rng = random.Random(RANDOM_SEED + 1)
    techs = []
    for tech_id, name, zone, specialties, shift in TECHNICIANS:
        home_wh = next((w for w in WAREHOUSES if w["zone"] == zone), WAREHOUSES[0])
        location = _point_in_zone(rng, zone)  # se consume siempre, para no alterar la secuencia del resto
        location = dict(PINNED_TECH_LOCATIONS.get(tech_id, location))
        techs.append(
            {
                "technician_id": tech_id,
                "user_id": f"u-tec-{tech_id.split('-')[1]}",
                "name": name,
                "zone": zone,
                "specialties": specialties,
                "location": location,
                "home_warehouse_id": home_wh["warehouse_id"],
                "available": True,
                "shift": shift,
                "current_load": 0,
                "seed_version": SEED_VERSION,
            }
        )
    return techs


def build_catalog() -> list[dict]:
    return [
        {
            "component_id": cid,
            "name": name,
            "specialty": specialty,
            "compatible_models": models,
            "cost_usd": cost,  # nombre que lee la analítica de A (contratos.md §9)
            "lead_time_days": lead,
            "seed_version": SEED_VERSION,
        }
        for cid, name, specialty, models, cost, lead in CATALOG
    ]


def _stock_limits(unit_cost: float) -> tuple[int, int]:
    if unit_cost < 200:
        return 10, 40
    if unit_cost < 2000:
        return 2, 8
    if unit_cost < 10000:
        return 1, 4
    return 1, 2


def _alert(stock: int, smin: int, smax: int) -> str:
    if stock < smin:
        return "low_stock"
    if stock > smax:
        return "overstock"
    return "none"


def build_inventory() -> list[dict]:
    rng = random.Random(RANDOM_SEED + 2)
    items = []
    for wh in WAREHOUSES:
        for cid, name, _spec, _models, cost, _lead in CATALOG:
            smin, smax = _stock_limits(cost)
            stock = INVENTORY_OVERRIDES.get((wh["warehouse_id"], cid), rng.randint(smin, smax))
            items.append(
                {
                    "warehouse_id": wh["warehouse_id"],  # nombre del OpenAPI (InventoryItem)
                    "location_id": wh["warehouse_id"],  # nombre que lee A (contratos.md §9)
                    "warehouse_name": wh["name"],
                    "zone": wh["zone"],
                    "component_id": cid,
                    "name": name,
                    "stock": stock,
                    "stock_min": smin,
                    "stock_max": smax,
                    "alert": _alert(stock, smin, smax),
                    "seed_version": SEED_VERSION,
                }
            )
    return items


def build_notification_rules() -> list[dict]:
    return [
        {
            "event_type": event_type,
            "role": role,
            "severity_min": severity_min,
            "channels": channels,
            "content_profile": profile,
            "throttle_minutes": throttle,
            "enabled": True,
            "seed_version": SEED_VERSION,
        }
        for event_type, role, severity_min, channels, profile, throttle in NOTIFICATION_RULES
    ]


def build_all() -> dict[str, list[dict]]:
    """Todos los datasets. Las claves coinciden con las entradas de KEY_SCHEMA en seed.py."""
    return {
        "machines": build_machines(),
        "machine_models": build_machine_models(),
        "technicians": build_technicians(),
        "catalog": build_catalog(),
        "inventory": build_inventory(),
        "notification_rules": build_notification_rules(),
        "warehouses": [dict(w) for w in WAREHOUSES],
    }
