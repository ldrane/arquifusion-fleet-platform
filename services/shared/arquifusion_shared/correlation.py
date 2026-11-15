"""correlation_id de punta a punta (contratos.md §1, Trazabilidad)."""
import re
import uuid

# F-35: un id de cliente solo se acepta con formato simple (evita log injection y ids enormes)
_VALID_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def _new() -> str:
    return str(uuid.uuid4())


def from_api_event(event: dict) -> str:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    value = headers.get("x-correlation-id")
    return value if isinstance(value, str) and _VALID_ID.fullmatch(value) else _new()


def from_eventbridge(event: dict) -> str:
    return (event.get("detail") or {}).get("correlation_id") or _new()


def from_any(event) -> str:
    """Para los handlers (#27): API Gateway (header), EventBridge (`detail.correlation_id`),
    invocación directa desde Step Functions (`correlation_id` en la raíz) o lote de Streams/SQS."""
    if not isinstance(event, dict):
        return _new()
    if "httpMethod" in event or "requestContext" in event:
        return from_api_event(event)
    if "detail-type" in event or "detail" in event:
        return from_eventbridge(event)
    return event.get("correlation_id") or _new()
