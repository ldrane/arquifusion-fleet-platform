"""Variables que usa el modelo de anomalías (RF-02, RF-09).

Simulador, `procesar` y `retrain` importan esta lista: el orden del vector es parte del contrato del modelo.
"""

# Variables crudas de TelemetryReading (contracts/openapi.yaml) que entran al modelo.
RAW_FEATURES: tuple[str, ...] = (
    "temperature_c",
    "vibration_mm_s",
    "pressure_bar",
    "fuel_rate_lph",
    "load_pct",
    "rpm",
    "speed_kmh",
)

# Variables derivadas, calculadas con `derive()`.
DERIVED_FEATURES: tuple[str, ...] = ("fuel_per_load",)

FEATURES: tuple[str, ...] = RAW_FEATURES + DERIVED_FEATURES

# Variables que se vigilan con z-score y reglas (capas 1 y 2); son las que se explican como top_factors.
MONITORED: tuple[str, ...] = ("temperature_c", "vibration_mm_s", "pressure_bar", "fuel_rate_lph", "rpm")


def derive(reading: dict) -> dict[str, float]:
    """Calcula las variables derivadas de una lectura."""
    load = max(float(reading.get("load_pct", 0.0)), 1.0)
    return {"fuel_per_load": float(reading["fuel_rate_lph"]) / load}


def to_vector(reading: dict) -> list[float]:
    """Convierte una lectura (formato API o fila del lake) al vector de entrada del modelo, en el orden de FEATURES."""
    derived = derive(reading)
    return [float(reading[f]) for f in RAW_FEATURES] + [derived[f] for f in DERIVED_FEATURES]
