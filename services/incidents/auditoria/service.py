"""auditoria (RNF-15, TRZ-02, RF-11.1). Contrato: contratos.md §3 y §9.1.

Consume por regla de EventBridge (bus `{p}-fleet-events`) los eventos de dominio:
- `arquifusion.incident` / `IncidentStateChanged` → escribe
  1. `{p}-audit-events`: `pk = incident#<incident_id>`, `sk = <occurred_at>#<event_id>` (append-only), y
  2. el historial del incidente en `{p}-incidents`: `pk = INC#<id>`, `sk = EVT#<occurred_at>#<event_id>`,
     `entity = incident_event`, `event_type`, `from`, `to`, `actor{}`, `occurred_at`, `correlation_id`
     (+ `technician_id`). Sin `incident_id`/`status`/`machine_id`/`detected_at` en la raíz (§9.1, #26).
- `arquifusion.processor` / `AnomalyDetected` y `arquifusion.heartbeat` / `MachineSilent` →
  `{p}-audit-events` con `pk = machine#<machine_id>`.

Idempotente: PutItem con `attribute_not_exists(pk)`; un reintento de EventBridge no duplica filas.
"""
import json
from decimal import Decimal


def _ddb(value):
    """float → Decimal para DynamoDB."""
    return json.loads(json.dumps(value), parse_float=Decimal)


def build_items(event: dict) -> tuple[dict, dict | None]:
    detail = event.get("detail") or {}
    data = detail.get("data") or {}
    detail_type = event.get("detail-type")
    event_id = detail.get("event_id") or event.get("id")
    occurred_at = detail.get("occurred_at") or event.get("time")
    sk = f"{occurred_at}#{event_id}"

    if detail_type == "IncidentStateChanged":
        entity, entity_id = "incident", data.get("incident_id")
    else:
        entity, entity_id = "machine", data.get("machine_id")
    if not entity_id:
        raise ValueError(f"Evento {detail_type} sin id de entidad")

    audit = _ddb(
        {
            "pk": f"{entity}#{entity_id}",
            "sk": sk,
            "entity": entity,
            "source": event.get("source"),
            "detail_type": detail_type,
            "event_id": event_id,
            "event_type": data.get("event_type") or detail_type,
            "occurred_at": occurred_at,
            "correlation_id": detail.get("correlation_id"),
            "actor": data.get("actor") or {"type": "system", "user_id": None, "role": None},
            "data": data,
        }
    )
    history = None
    if detail_type == "IncidentStateChanged":
        history = {
            "pk": f"INC#{entity_id}",
            "sk": f"EVT#{sk}",
            "entity": "incident_event",
            "event_id": event_id,
            "event_type": data.get("event_type"),
            "from": data.get("from"),
            "to": data.get("to"),
            "actor": data.get("actor") or {"type": "system", "user_id": None, "role": None},
            "occurred_at": occurred_at,
            "correlation_id": detail.get("correlation_id"),
        }
        if data.get("technician_id"):
            history["technician_id"] = data["technician_id"]
    return audit, history


def _put_once(table, item: dict) -> bool:
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
        return True
    except Exception as exc:  # noqa: BLE001
        if getattr(exc, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise


def _default_deps() -> dict:  # pragma: no cover
    import boto3
    from arquifusion_shared import config

    ddb = boto3.resource("dynamodb")
    return {"audit": ddb.Table(config.table("audit-events")), "incidents": ddb.Table(config.table("incidents"))}


def run(event: dict, deps: dict | None = None) -> dict:
    deps = deps or _default_deps()
    audit, history = build_items(event)
    written = {"audit": _put_once(deps["audit"], audit)}
    if history is not None:
        written["history"] = _put_once(deps["incidents"], history)
    return written
