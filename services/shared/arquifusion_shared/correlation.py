"""correlation_id de punta a punta (contratos.md §1, Trazabilidad)."""
import uuid


def from_api_event(event: dict) -> str:
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    return headers.get("x-correlation-id") or str(uuid.uuid4())


def from_eventbridge(event: dict) -> str:
    return event.get("detail", {}).get("correlation_id") or str(uuid.uuid4())
