"""Capa 1: reglas por umbral según el tipo de máquina (RF-02.1).

Umbrales en SSM `/arquifusion/{stage}/thresholds/{machine_type}` (JSON), con caché.
Si el parámetro no existe, se usan los valores de `thresholds_default.json`.
Formato: {"<variable>": {"warn_high", "crit_high", "warn_low"?, "crit_low"?}}
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

DEFAULTS_FILE = Path(__file__).resolve().parents[1] / "thresholds_default.json"

WARN, CRIT = "warn", "crit"


@dataclass(frozen=True)
class RuleHit:
    variable: str
    level: str  # warn | crit
    direction: str  # high | low


def evaluate(reading: dict, thresholds: dict) -> list[RuleHit]:
    """Devuelve las variables que superan su umbral, con el nivel más alto alcanzado."""
    hits = []
    for variable, limits in thresholds.items():
        value = reading.get(variable)
        if value is None:
            continue
        value = float(value)
        if "crit_high" in limits and value >= limits["crit_high"]:
            hits.append(RuleHit(variable, CRIT, "high"))
        elif "crit_low" in limits and value <= limits["crit_low"]:
            hits.append(RuleHit(variable, CRIT, "low"))
        elif "warn_high" in limits and value >= limits["warn_high"]:
            hits.append(RuleHit(variable, WARN, "high"))
        elif "warn_low" in limits and value <= limits["warn_low"]:
            hits.append(RuleHit(variable, WARN, "low"))
    return hits


class ThresholdProvider:
    """Entrega los umbrales de un tipo de máquina con caché de `ttl_s` segundos."""

    def __init__(
        self, fetch: Callable[[str], str | None], ttl_s: int = 300, clock: Callable[[], float] = time.monotonic
    ):
        self._fetch = fetch  # machine_type -> JSON de SSM o None si no existe
        self._ttl_s = ttl_s
        self._clock = clock
        self._cache: dict[str, tuple[float, dict]] = {}
        self._defaults = json.loads(DEFAULTS_FILE.read_text())

    def get(self, machine_type: str) -> dict:
        cached = self._cache.get(machine_type)
        now = self._clock()
        if cached and now - cached[0] < self._ttl_s:
            return cached[1]
        raw = self._fetch(machine_type)
        thresholds = json.loads(raw) if raw else self._defaults.get(machine_type, {})
        self._cache[machine_type] = (now, thresholds)
        return thresholds
