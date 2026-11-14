"""Variables de entorno con la convención única de contratos.md §1.1 (#23).

`table("incidents")` → valor de `TABLE_INCIDENTS` (nombre completo de la tabla).
Prohibido leer `TABLE_PREFIX`, `INCIDENTS_TABLE` y similares.
"""
import os

TABLES = (
    "machines",
    "machine-state",
    "idempotency",
    "anomalies",
    "incidents",
    "technicians",
    "inventory",
    "catalog",
    "warehouses",
    "notification-rules",
    "audit-events",
    "maintenance-records",
    "insights",
)


def table_env(name: str) -> str:
    """`notification-rules` → `TABLE_NOTIFICATION_RULES`."""
    return "TABLE_" + name.replace("-", "_").upper()


def table(name: str) -> str:
    """Nombre físico de la tabla. Falla con KeyError claro si la Lambda no tiene la variable."""
    var = table_env(name)
    try:
        return os.environ[var]
    except KeyError as exc:
        raise KeyError(f"Falta la variable de entorno {var} (contratos.md §1.1)") from exc


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def event_bus_name() -> str:
    return os.environ["EVENT_BUS_NAME"]


def default_operation_id() -> str:
    return os.environ.get("DEFAULT_OPERATION_ID", "OP-01")
