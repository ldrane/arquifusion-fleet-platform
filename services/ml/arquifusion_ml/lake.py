"""Esquema del data lake de telemetría (RNF-05, ESC-08).

Lo escriben Firehose (desde `procesar`) y el generador de historial del simulador; lo leen Athena y `retrain`.
Es también el esquema de la tabla Glue `telemetry_raw`. Partición: operation_id / dt / machine_type.
"""

# (columna, tipo Glue/Athena). El orden importa para Parquet y Glue.
LAKE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("machine_id", "string"),
    ("model", "string"),
    ("ts", "timestamp"),
    ("lat", "double"),
    ("lon", "double"),
    ("zone", "string"),
    ("operating_hours", "double"),
    ("temperature_c", "double"),
    ("vibration_mm_s", "double"),
    ("pressure_bar", "double"),
    ("fuel_rate_lph", "double"),
    ("load_pct", "double"),
    ("speed_kmh", "double"),
    ("rpm", "double"),
    ("state", "string"),
    ("sim_scenario", "string"),  # etiqueta del simulador: null = lectura normal. El modelo NO la usa.
    ("health_score", "int"),  # calculado por `procesar`; null en el historial sintético
    ("severity", "string"),  # calculado por `procesar`; null en el historial sintético
    ("correlation_id", "string"),
)

PARTITION_KEYS: tuple[tuple[str, str], ...] = (
    ("operation_id", "string"),
    ("dt", "string"),  # YYYY-MM-DD (UTC)
    ("machine_type", "string"),  # enum MachineType del OpenAPI
)

TELEMETRY_PREFIX = "telemetry"


def flatten_reading(reading: dict) -> dict:
    """Convierte una TelemetryReading (formato API, con `location` anidado) a una fila del lake, sin particiones."""
    loc = reading.get("location", {})
    row = {name: reading.get(name) for name, _ in LAKE_COLUMNS}
    row.update(ts=reading["timestamp"], lat=loc.get("lat"), lon=loc.get("lon"), zone=loc.get("zone"))
    return row


def partition_prefix(operation_id: str, dt: str, machine_type: str) -> str:
    """Prefijo S3 de una partición, igual al que usa el dynamic partitioning de Firehose."""
    return f"{TELEMETRY_PREFIX}/operation_id={operation_id}/dt={dt}/machine_type={machine_type}/"
