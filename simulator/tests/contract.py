"""Validación mínima de una lectura contra el schema TelemetryReading de contracts/openapi.yaml."""

import re
from datetime import datetime

_JSON_TYPES = {"string": str, "number": (int, float), "integer": int, "object": dict}


def _resolve(schema: dict, schemas: dict) -> dict:
    ref = schema.get("$ref")
    return schemas[ref.rsplit("/", 1)[1]] if ref else schema


def validate(value, schema: dict, schemas: dict, path: str = "reading") -> None:
    """Valida tipo, required, additionalProperties, enum, rangos, pattern y date-time."""
    schema = _resolve(schema, schemas)
    if value is None:
        assert schema.get("nullable"), f"{path}: null no permitido"
        return
    if "enum" in schema:
        assert value in schema["enum"], f"{path}: {value!r} fuera de {schema['enum']}"
    expected = _JSON_TYPES.get(schema.get("type"))
    if expected:
        assert isinstance(value, expected) and not isinstance(value, bool), f"{path}: tipo {type(value)}"
    if "minimum" in schema:
        assert value >= schema["minimum"], f"{path}: {value} < {schema['minimum']}"
    if "maximum" in schema:
        assert value <= schema["maximum"], f"{path}: {value} > {schema['maximum']}"
    if "pattern" in schema:
        assert re.match(schema["pattern"], value), f"{path}: {value} no cumple {schema['pattern']}"
    if schema.get("format") == "date-time":
        datetime.fromisoformat(value)
    if schema.get("type") == "object":
        props = schema.get("properties", {})
        missing = set(schema.get("required", [])) - set(value)
        assert not missing, f"{path}: faltan {missing}"
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            assert not extra, f"{path}: campos no permitidos {extra}"
        for key, sub in props.items():
            if key in value:
                validate(value[key], sub, schemas, f"{path}.{key}")
