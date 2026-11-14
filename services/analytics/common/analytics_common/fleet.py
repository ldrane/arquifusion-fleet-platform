"""Parámetros de la flota para la analítica, leídos del catálogo `MODEL#<model>` (contratos.md §9, hallazgo #13).

La fuente de verdad es el ítem `catalog pk=MODEL#<model_id>` del seed v2: `maintenance_interval_h` (250 h, o 500 h en
camiones), `payload_t` (t por ciclo; 0 en bulldozer/perforadora) y `nominal{variable: [media, desv]}`.
Las constantes de abajo son solo el respaldo cuando un modelo no está en el catálogo, y replican el seed.
"""

from dataclasses import dataclass, field

from boto3.dynamodb.conditions import Attr

from analytics_common.dynamo import scan_all

MODEL_PREFIX = "MODEL#"

# Respaldo por tipo cuando el modelo no está en el catálogo (mismos valores que scripts/seed_data.py).
SERVICE_INTERVAL_HOURS: dict[str, float] = {
    "excavator": 250.0,
    "mining_truck": 500.0,
    "loader": 250.0,
    "bulldozer": 250.0,
    "drill": 250.0,
}
DEFAULT_SERVICE_INTERVAL_HOURS = 250.0
NOMINAL_HOURS_PER_DAY = 16.0  # uso diario con el que el seed calcula `next_maintenance_at` (calendario fijo)

# Toneladas por hora a 100 % de carga cuando no hay `payload_t` (bulldozer y perforadora mueven/abren material
# sin carga útil propia) o el modelo no está en el catálogo.
CAPACITY_TPH: dict[str, float] = {
    "excavator": 400.0,
    "mining_truck": 220.0,
    "loader": 300.0,
    "bulldozer": 250.0,
    "drill": 120.0,
}
DEFAULT_CAPACITY_TPH = 250.0
# Ciclos de carga por hora a 100 % de carga: capacidad = payload_t × ciclos (solo tipos con carga útil).
CYCLES_PER_HOUR: dict[str, float] = {"excavator": 120.0, "mining_truck": 3.0, "loader": 45.0}

FUEL_PRICE_USD_PER_L = 1.10
AT_RISK_HEALTH = 50


@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    machine_type: str | None
    payload_t: float | None
    maintenance_interval_h: float | None
    nominal: dict[str, tuple[float, float]] = field(default_factory=dict, hash=False)


@dataclass(frozen=True)
class Catalog:
    """Modelos de máquina del catálogo. `Catalog()` vacío = solo respaldos por tipo."""

    models: dict[str, ModelInfo] = field(default_factory=dict, hash=False)

    @classmethod
    def from_items(cls, items: list[dict]) -> "Catalog":
        models = {}
        for item in items:
            is_model = str(item.get("pk", "")).startswith(MODEL_PREFIX) or item.get("entity") == "machine_models"
            model_id = item.get("model_id") or str(item.get("pk", "")).removeprefix(MODEL_PREFIX)
            if not is_model or not model_id:
                continue
            nominal = {v: (float(ms[0]), float(ms[1])) for v, ms in (item.get("nominal") or {}).items()}
            models[model_id] = ModelInfo(
                model_id=model_id,
                machine_type=item.get("type"),
                payload_t=_float(item.get("payload_t")),
                maintenance_interval_h=_float(item.get("maintenance_interval_h")),
                nominal=nominal,
            )
        return cls(models)

    def get(self, model: str | None) -> ModelInfo | None:
        return self.models.get(model or "")

    def service_interval(self, model: str | None, machine_type: str | None) -> float:
        info = self.get(model)
        if info and info.maintenance_interval_h:
            return info.maintenance_interval_h
        return service_interval(machine_type)

    def capacity_tph(self, model: str | None, machine_type: str | None) -> float:
        info = self.get(model)
        mtype = machine_type or (info.machine_type if info else None)
        if info and info.payload_t and mtype in CYCLES_PER_HOUR:
            return info.payload_t * CYCLES_PER_HOUR[mtype]
        return capacity_tph(mtype)

    def nominal_mean(self, model: str | None, variable: str) -> float | None:
        info = self.get(model)
        return info.nominal[variable][0] if info and variable in info.nominal else None


def _float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def load_catalog(catalog_table) -> Catalog:
    """Lee solo los ítems `MODEL#…` de `{p}-catalog`."""
    return Catalog.from_items(scan_all(catalog_table, FilterExpression=Attr("pk").begins_with(MODEL_PREFIX)))


def capacity_tph(machine_type: str | None) -> float:
    return CAPACITY_TPH.get(machine_type or "", DEFAULT_CAPACITY_TPH)


def service_interval(machine_type: str | None) -> float:
    return SERVICE_INTERVAL_HOURS.get(machine_type or "", DEFAULT_SERVICE_INTERVAL_HOURS)
