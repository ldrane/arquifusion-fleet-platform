"""correlation_id de punta a punta (contratos.md §1, Trazabilidad)."""
import uuid


def _new() -> str:
    return str(uuid.uuid4())


def from_api_event(event: dict) -> str:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    return headers.get("x-correlation-id") or _new()


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
