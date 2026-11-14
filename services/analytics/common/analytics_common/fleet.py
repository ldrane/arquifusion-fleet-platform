"""Parámetros de referencia de la flota usados por la analítica (ajustables con datos reales del cliente)."""

# Toneladas movidas por hora a 100 % de carga, por tipo de máquina (MachineType del OpenAPI).
CAPACITY_TPH: dict[str, float] = {
    "excavator": 400.0,
    "mining_truck": 220.0,
    "loader": 300.0,
    "bulldozer": 250.0,
    "drill": 120.0,
}
DEFAULT_CAPACITY_TPH = 250.0

# Intervalo de mantenimiento preventivo del fabricante, en horas de operación.
SERVICE_INTERVAL_HOURS: dict[str, float] = {
    "excavator": 500.0,
    "mining_truck": 500.0,
    "loader": 500.0,
    "bulldozer": 500.0,
    "drill": 400.0,
}
DEFAULT_SERVICE_INTERVAL_HOURS = 500.0
NOMINAL_HOURS_PER_DAY = 10.0  # supuesto del calendario fijo tradicional

FUEL_PRICE_USD_PER_L = 1.10
AT_RISK_HEALTH = 50


def capacity_tph(machine_type: str | None) -> float:
    return CAPACITY_TPH.get(machine_type or "", DEFAULT_CAPACITY_TPH)


def service_interval(machine_type: str | None) -> float:
    return SERVICE_INTERVAL_HOURS.get(machine_type or "", DEFAULT_SERVICE_INTERVAL_HOURS)
