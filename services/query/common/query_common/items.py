"""De ítems DynamoDB a los shapes públicos (openapi.yaml `components.schemas`, contratos.md §5 y §9).

La API (api_lectura) y la réplica de Firestore (replicar) usan las MISMAS proyecciones,
así el front recibe el mismo esquema por REST y por `onSnapshot`.
Reglas:
- Nunca salen `pk`, `sk`, `entity` ni los secretos `ack_token`, `resolve_token`,
  `execution_arn` (dynamodb.md, Reglas 2).
- Los `Decimal` salen como número JSON: int si es entero, float si no (#25).
- Los campos que el seed omite (None) salen como `null` para respetar el shape del front (`frontend/src/api/types.ts`).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

SECRET_FIELDS = frozenset({"ack_token", "resolve_token", "execution_arn"})
INTERNAL_FIELDS = frozenset({"pk", "sk", "entity"}) | SECRET_FIELDS

SEVERITY_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

# --------------------------------------------------------------------------- campos por schema
MACHINE_FIELDS = (
    "machine_id",
    "model",
    "type",
    "location",
    "status",
    "severity",
    "health_score",
    "last_seen_at",
    "open_incident_id",  # en Machine del front (types.ts) y en Firestore: el mapa marca las máquinas con incidente
)
MACHINE_DETAIL_FIELDS = MACHINE_FIELDS + (
    "failure_probability",
    "rul_hours",
    "operating_hours",
    "last_maintenance_at",
    "next_maintenance_at",
    "latest_reading",
    "top_factors",
    "model_version",
)
INCIDENT_FIELDS = (
    "incident_id",
    "parent_incident_id",
    "child_incident_ids",
    "machine_id",
    "machine_ids",
    "zone",
    "severity",
    "status",
    "escalated",
    "is_recurrence",
    "assigned_technician_id",
    "technician_score",
    "ai_diagnosis",
    "resolution_summary",
    "detected_at",
    "assigned_at",
    "accepted_at",
    "resolved_at",
    "downtime_minutes",
    "components_replaced",
    "cost_usd",
    "chat_channel_id",
)
TECHNICIAN_FIELDS = (
    "technician_id",
    "name",
    "specialties",
    "location",
    "available",
    "shift",
    "current_load",
)
INVENTORY_FIELDS = ("warehouse_id", "component_id", "name", "stock", "stock_min", "stock_max", "alert")

_LIST_DEFAULTS = {"child_incident_ids", "machine_ids", "components_replaced", "top_factors", "specialties"}
_BOOL_DEFAULTS = {"escalated", "is_recurrence"}


def plain(value: Any) -> Any:
    """Decimal -> int/float, set -> list, recursivo. Deja el resto igual."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(plain(v) for v in value)
    return value


def _project(item: dict, fields: tuple[str, ...]) -> dict:
    out = {}
    for f in fields:
        v = item.get(f)
        if v is None:
            v = [] if f in _LIST_DEFAULTS else (False if f in _BOOL_DEFAULTS else None)
        out[f] = plain(v)
    return out


def _location_with_zone(location: Any, zone: Any) -> dict | None:
    """`location.zone` siempre presente (#11).

    Si el ítem trae `{lat, lon}` sin zona, se usa el `zone` de primer nivel.
    """
    if not isinstance(location, dict):
        return None
    loc = plain(dict(location))
    if not loc.get("zone") and zone:
        loc["zone"] = zone
    return loc


def machine(item: dict, detail: bool = False) -> dict:
    out = _project(item, MACHINE_DETAIL_FIELDS if detail else MACHINE_FIELDS)
    out["location"] = _location_with_zone(item.get("location") or item.get("home_location"), item.get("zone"))
    return out


def machine_zone(item: dict) -> str | None:
    return item.get("zone") or (item.get("location") or {}).get("zone")


def incident(item: dict) -> dict:
    out = _project(item, INCIDENT_FIELDS)
    if not out["machine_ids"] and out["machine_id"]:
        out["machine_ids"] = [out["machine_id"]]  # #26: el OpenAPI expone machine_ids[]
    if not out["machine_id"] and out["machine_ids"]:
        out["machine_id"] = out["machine_ids"][0]
    return out


def technician(item: dict) -> dict:
    out = _project(item, TECHNICIAN_FIELDS)
    out["location"] = _location_with_zone(item.get("location"), item.get("zone"))
    out["available"] = bool(out["available"])
    out["current_load"] = out["current_load"] or 0
    return out


def inventory_alert(item: dict) -> str:
    stock, lo, hi = (plain(item.get(k)) for k in ("stock", "stock_min", "stock_max"))
    if stock is None:
        return "none"
    if lo is not None and stock < lo:
        return "low_stock"
    if hi is not None and stock > hi:
        return "overstock"
    return "none"


def inventory(item: dict) -> dict:
    out = _project(item, INVENTORY_FIELDS)
    out["warehouse_id"] = out["warehouse_id"] or item.get("location_id") or item.get("pk")
    out["alert"] = inventory_alert(item)
    return out
