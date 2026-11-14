"""Capa 1: reglas por umbral según el MODELO de la máquina (RF-02.1, hallazgo #2).

Los umbrales se derivan del `nominal` [μ, σ] de cada modelo (catalog `MODEL#<model>`, seed v2):
    warn_high = μ + 3σ · crit_high = μ + 4σ
    warn_low  = μ − 3σ · crit_low  = μ − 4σ   (solo `pressure_bar` y `rpm`, y solo con la máquina operando)
Así la operación nominal del seed no dispara alarmas y una degradación real sí.

Fuente, en orden (contratos.md §9):
1. SSM `/arquifusion/{stage}/thresholds/{model}` (JSON, override opcional; infra/ingest lo publica con los valores
   derivados y no pisa cambios manuales).
2. `thresholds_default.json` (generado desde `contracts/fixtures/seed/machine_models.json`):
   `models.<model>` y, si el modelo no existe, `types.<machine_type>` (el umbral más permisivo de su tipo).

Formato de un juego de umbrales: {"<variable>": {"warn_high", "crit_high", "warn_low"?, "crit_low"?}}
Regenerar los defaults: `python services/ingest/procesar/ingest_procesar/rules.py`.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULTS_FILE = Path(__file__).resolve().parents[1] / "thresholds_default.json"

WARN, CRIT = "warn", "crit"
WARN_SIGMAS, CRIT_SIGMAS = 3.0, 4.0
HIGH_VARIABLES = ("temperature_c", "vibration_mm_s", "pressure_bar", "fuel_rate_lph", "rpm")
LOW_VARIABLES = ("pressure_bar", "rpm")  # caída de presión hidráulica o de RPM (eléctrica)
LOW_RULE_STATES = ("operating",)  # detenida, en espera o en mantenimiento, presión y RPM bajas son normales


@dataclass(frozen=True)
class RuleHit:
    variable: str
    level: str  # warn | crit
    direction: str  # high | low


def derive_thresholds(nominal: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    """Umbrales de un modelo a partir de su `nominal` {variable: [media, desviación]}."""
    out: dict[str, dict[str, float]] = {}
    for variable in HIGH_VARIABLES:
        if variable not in nominal:
            continue
        mu, sd = (float(x) for x in nominal[variable])
        limits = {"warn_high": round(mu + WARN_SIGMAS * sd, 2), "crit_high": round(mu + CRIT_SIGMAS * sd, 2)}
        if variable in LOW_VARIABLES:
            limits["warn_low"] = round(max(mu - WARN_SIGMAS * sd, 0.0), 2)
            limits["crit_low"] = round(max(mu - CRIT_SIGMAS * sd, 0.0), 2)
        out[variable] = limits
    return out


def build_defaults(machine_models: list[dict]) -> dict:
    """`thresholds_default.json`: umbrales por modelo y, de respaldo, el más permisivo de cada tipo."""
    models = {m["model_id"]: derive_thresholds(m["nominal"]) for m in machine_models}
    types: dict[str, dict[str, dict[str, float]]] = {}
    for m in machine_models:
        merged = types.setdefault(m["type"], {})
        for variable, limits in models[m["model_id"]].items():
            current = merged.setdefault(variable, dict(limits))
            for key, value in limits.items():
                current[key] = max(current[key], value) if key.endswith("_high") else min(current[key], value)
    return {"models": dict(sorted(models.items())), "types": dict(sorted(types.items()))}


def evaluate(reading: dict, thresholds: dict) -> list[RuleHit]:
    """Devuelve las variables que superan su umbral, con el nivel más alto alcanzado."""
    check_low = reading.get("state", "operating") in LOW_RULE_STATES
    hits = []
    for variable, limits in thresholds.items():
        value = reading.get(variable)
        if value is None:
            continue
        value = float(value)
        if "crit_high" in limits and value >= limits["crit_high"]:
            hits.append(RuleHit(variable, CRIT, "high"))
        elif check_low and "crit_low" in limits and value <= limits["crit_low"]:
            hits.append(RuleHit(variable, CRIT, "low"))
        elif "warn_high" in limits and value >= limits["warn_high"]:
            hits.append(RuleHit(variable, WARN, "high"))
        elif check_low and "warn_low" in limits and value <= limits["warn_low"]:
            hits.append(RuleHit(variable, WARN, "low"))
    return hits


class ThresholdProvider:
    """Entrega los umbrales de un modelo con caché de `ttl_s` segundos."""

    def __init__(
        self,
        fetch: Callable[[str], str | None],
        ttl_s: int = 300,
        clock: Callable[[], float] = time.monotonic,
        defaults: dict | None = None,
    ):
        self._fetch = fetch  # model -> JSON de SSM o None si no existe
        self._ttl_s = ttl_s
        self._clock = clock
        self._cache: dict[str, tuple[float, dict]] = {}
        self._defaults = defaults or json.loads(DEFAULTS_FILE.read_text())

    def default_for(self, model: str | None, machine_type: str | None = None) -> dict:
        return self._defaults["models"].get(model or "") or self._defaults["types"].get(machine_type or "", {})

    def get(self, model: str | None, machine_type: str | None = None) -> dict:
        key = model or f"type:{machine_type}"
        cached = self._cache.get(key)
        now = self._clock()
        if cached and now - cached[0] < self._ttl_s:
            return cached[1]
        raw = self._fetch(model) if model else None
        thresholds = json.loads(raw) if raw else self.default_for(model, machine_type)
        self._cache[key] = (now, thresholds)
        return thresholds


def seed_models_file() -> Path:
    """`machine_models.json` del seed (solo existe en el repo, no dentro de la imagen de la Lambda)."""
    return Path(__file__).resolve().parents[4] / "contracts" / "fixtures" / "seed" / "machine_models.json"


if __name__ == "__main__":
    defaults = build_defaults(json.loads(seed_models_file().read_text()))
    DEFAULTS_FILE.write_text(json.dumps(defaults, indent=2, ensure_ascii=False) + "\n")
    print(f"{DEFAULTS_FILE}: {len(defaults['models'])} modelos, {len(defaults['types'])} tipos")
