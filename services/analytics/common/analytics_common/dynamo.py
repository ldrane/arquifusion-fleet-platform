"""Lectura y escritura en DynamoDB para la analítica (conversión Decimal ↔ float)."""

import json
from decimal import Decimal


def plain(value):
    """Decimal → int/float, recursivo."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    return value


def to_dynamo(value):
    """float → Decimal (DynamoDB no acepta float). Fechas y otros tipos se serializan como texto."""
    return json.loads(json.dumps(value, default=str), parse_float=Decimal)


def scan_all(table, **kwargs) -> list[dict]:
    items, start = [], None
    while True:
        page = table.scan(**kwargs, **({"ExclusiveStartKey": start} if start else {}))
        items.extend(page.get("Items", []))
        start = page.get("LastEvaluatedKey")
        if not start:
            return [plain(i) for i in items]


def key_of(table, item: dict) -> dict:
    """Clave primaria de `item` según el key schema real de la tabla (no asume nombres de atributos)."""
    return {k["AttributeName"]: item[k["AttributeName"]] for k in table.key_schema}
