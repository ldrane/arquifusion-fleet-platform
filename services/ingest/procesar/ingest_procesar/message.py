"""Parseo del mensaje SQS que deja API Gateway (RF-01.3).

El mapping template de `POST /telemetry` envuelve el lote así:
    {"correlation_id": "<requestId>", "received_at": "<epoch ms>", "batch": {"readings": [...]}}
"""

import json
import uuid
from dataclasses import dataclass

REQUIRED = (
    "machine_id",
    "type",
    "timestamp",
    "location",
    "temperature_c",
    "vibration_mm_s",
    "pressure_bar",
    "fuel_rate_lph",
    "load_pct",
    "speed_kmh",
    "rpm",
    "state",
)


class InvalidMessage(ValueError):
    """El cuerpo del mensaje no tiene el formato esperado: se reintenta y termina en la DLQ."""


@dataclass(frozen=True)
class Envelope:
    correlation_id: str
    readings: list[dict]
    invalid: int  # lecturas descartadas por campos faltantes


def parse(body: str) -> Envelope:
    """Valida el envoltorio y separa las lecturas válidas.

    API Gateway ya validó el JSON Schema, así que una lectura incompleta aquí es excepcional:
    se descarta y se cuenta, sin bloquear al resto del lote.
    """
    try:
        payload = json.loads(body)
        readings = payload["batch"]["readings"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise InvalidMessage(f"Mensaje SQS sin batch.readings: {exc}") from exc
    if not isinstance(readings, list):
        raise InvalidMessage("batch.readings no es una lista")

    valid = [r for r in readings if isinstance(r, dict) and all(k in r for k in REQUIRED)]
    correlation_id = payload.get("correlation_id") or str(uuid.uuid4())
    return Envelope(correlation_id=correlation_id, readings=valid, invalid=len(readings) - len(valid))
