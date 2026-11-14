"""Envoltorio estándar de respuestas (contratos.md §1, §1.2). Prohibido armar respuestas a mano.

- CORS (#5): todas las respuestas (éxito y error) llevan los headers de §1.2. El origen sale de `CORS_ORIGIN`.
- Números (#25): los `Decimal` de DynamoDB se serializan como número JSON (int si es entero, float si no).
"""
import json
import os
from decimal import Decimal

from .errors import ApiError

CORS_ALLOW_HEADERS = "Authorization,Content-Type,X-Correlation-Id,X-Api-Key"
CORS_ALLOW_METHODS = "GET,POST,PUT,OPTIONS"
CORS_EXPOSE_HEADERS = "X-Correlation-Id"


def cors_headers() -> dict:
    """Headers CORS de contratos.md §1.2. Se lee `CORS_ORIGIN` en cada llamada (los tests lo cambian)."""
    return {
        "Access-Control-Allow-Origin": os.environ.get("CORS_ORIGIN", "*"),
        "Access-Control-Allow-Headers": CORS_ALLOW_HEADERS,
        "Access-Control-Allow-Methods": CORS_ALLOW_METHODS,
        "Access-Control-Expose-Headers": CORS_EXPOSE_HEADERS,
    }


def _json_default(value):
    if isinstance(value, Decimal):
        # int si es entero (3 o 3.0 en DynamoDB), float si tiene decimales
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, set):  # sets de DynamoDB (SS/NS)
        return sorted(value, key=str)
    return str(value)


def dumps(body) -> str:
    """json.dumps con la serialización del contrato (Decimal → número). Úsalo también fuera de API Gateway."""
    return json.dumps(body, ensure_ascii=False, default=_json_default)


def _resp(status: int, body: dict, correlation_id: str) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "X-Correlation-Id": correlation_id,
            **cors_headers(),
        },
        "body": dumps(body),
    }


def ok(data, correlation_id: str, meta: dict | None = None, status: int = 200) -> dict:
    return _resp(status, {"data": data, "meta": meta or {}}, correlation_id)


def error(err: ApiError, correlation_id: str) -> dict:
    body = {"error": {"code": err.code, "message": err.message, "details": err.details}, "correlation_id": correlation_id}
    return _resp(err.status, body, correlation_id)
