"""Capa 2: baseline EWMA y z-score, propio de la máquina y de su cohorte (RF-02.2, RF-09, ESC-07).

Cada variable guarda media y varianza exponencialmente ponderadas:
    mean' = mean + α·(x − mean)
    var'  = (1 − α)·(var + α·(x − mean)²)
El z-score se calcula contra el baseline ANTERIOR a la lectura, para que una anomalía no se "normalice" a sí misma.
"""

import math
from dataclasses import dataclass, field

MIN_STD = 1e-6
# Piso de desviación relativo a la media: evita z-scores enormes por ruido cuando la varianza
# estimada es casi cero (máquina muy estable o pocas lecturas). 2 % de la media.
REL_STD_FLOOR = 0.02


@dataclass
class Stat:
    mean: float
    var: float
    n: int


@dataclass
class Baseline:
    """Baseline de un conjunto de variables. Se serializa como mapa en DynamoDB."""

    stats: dict[str, Stat] = field(default_factory=dict)

    def zscore(self, variable: str, value: float, warmup: int) -> float:
        """z-score de `value` contra el baseline. 0 si aún no hay suficientes lecturas (warm-up)."""
        stat = self.stats.get(variable)
        if stat is None or stat.n < warmup:
            return 0.0
        std = max(math.sqrt(stat.var), abs(stat.mean) * REL_STD_FLOOR, MIN_STD)
        return (value - stat.mean) / std

    def update(self, values: dict[str, float], alpha: float) -> None:
        for variable, x in values.items():
            stat = self.stats.get(variable)
            if stat is None:
                self.stats[variable] = Stat(mean=x, var=0.0, n=1)
                continue
            diff = x - stat.mean
            # Media simple durante el warm-up para no sesgar el baseline con la primera lectura.
            weight = max(alpha, 1.0 / (stat.n + 1))
            stat.mean += weight * diff
            stat.var = (1 - weight) * (stat.var + weight * diff * diff)
            stat.n += 1

    def to_item(self) -> dict:
        return {v: {"mean": s.mean, "var": s.var, "n": s.n} for v, s in self.stats.items()}

    @classmethod
    def from_item(cls, item: dict | None) -> "Baseline":
        if not item:
            return cls()
        return cls({v: Stat(float(s["mean"]), float(s["var"]), int(s["n"])) for v, s in item.items()})


def zscores(baseline: Baseline, values: dict[str, float], warmup: int) -> dict[str, float]:
    return {v: baseline.zscore(v, x, warmup) for v, x in values.items()}
