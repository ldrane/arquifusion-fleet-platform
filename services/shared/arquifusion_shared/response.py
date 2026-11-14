"""Envoltorio estándar de respuestas (contratos.md §1). Prohibido armar respuestas a mano."""
import json

from .errors import ApiError


def _resp(status: int, body: dict, correlation_id: str) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", "X-Correlation-Id": correlation_id},
        "body": json.dumps(body, ensure_ascii=False, default=str),
    }


def ok(data, correlation_id: str, meta: dict | None = None, status: int = 200) -> dict:
    return _resp(status, {"data": data, "meta": meta or {}}, correlation_id)


def error(err: ApiError, correlation_id: str) -> dict:
    body = {"error": {"code": err.code, "message": err.message, "details": err.details}, "correlation_id": correlation_id}
    return _resp(err.status, body, correlation_id)
