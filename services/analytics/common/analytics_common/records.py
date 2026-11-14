"""Vista normalizada de `maintenance-records` (requerimientos §5.4 MaintenanceRecord).

El esquema exacto lo define la Persona B; se aceptan los alias en inglés y español para no acoplarse.
"""

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Record:
    machine_id: str
    kind: str  # preventivo | correctivo
    day: date
    operating_hours: float | None
    components: dict[str, int]  # component_id -> unidades
    cost_usd: float


def _first(item: dict, *names):
    for name in names:
        if item.get(name) is not None:
            return item[name]
    return None


def _day(value) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _components(value) -> dict[str, int]:
    out: dict[str, int] = {}
    for entry in value or []:
        if isinstance(entry, str):
            out[entry] = out.get(entry, 0) + 1
        elif isinstance(entry, dict) and entry.get("component_id"):
            qty = int(_first(entry, "quantity", "qty", "units") or 1)
            out[entry["component_id"]] = out.get(entry["component_id"], 0) + qty
    return out


def normalize(items: list[dict]) -> list[Record]:
    """Convierte ítems crudos en Record. Ignora los que no tienen máquina o fecha."""
    records = []
    for item in items:
        day = _day(_first(item, "performed_at", "date", "fecha", "resolved_at"))
        machine_id = item.get("machine_id")
        if not machine_id or day is None:
            continue
        kind = str(_first(item, "type", "tipo", "kind") or "correctivo").lower()
        hours = _first(item, "operating_hours", "hours_at_maintenance", "horas_al_momento")
        records.append(
            Record(
                machine_id=machine_id,
                kind="preventivo" if kind.startswith(("prev", "pm")) else "correctivo",
                day=day,
                operating_hours=float(hours) if hours is not None else None,
                components=_components(_first(item, "components", "componentes", "components_replaced")),
                cost_usd=float(_first(item, "cost_usd", "costo", "cost") or 0.0),
            )
        )
    return records
