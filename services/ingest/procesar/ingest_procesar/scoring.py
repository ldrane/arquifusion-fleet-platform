"""Combinación de las 3 capas en riesgo, health score, severidad y top-3 factores (RF-02.3, RF-02.5, RF-09).

Cada capa aporta un riesgo independiente entre 0 y 1 y se combinan como probabilidades:
    riesgo = 1 − (1 − r_reglas)·(1 − r_estadística)·(1 − r_ml)
Así, varias señales moderadas a la vez (temperatura + vibración + combustible) suman más que
cualquiera por separado, que es justamente el comportamiento conjunto que pide el cliente.
"""

from dataclasses import dataclass

from .rules import CRIT, WARN, RuleHit

Z_START, Z_SPAN = 2.0, 3.0  # |z| = 2 → 0 de riesgo; |z| = 5 → riesgo 1 por variable
RULE_RISK = {WARN: 0.4, CRIT: 0.7}  # 1 umbral crítico = high; 2 o más = critical (piso)
SEVERITY_ORDER = ("info", "low", "medium", "high", "critical")
SEVERITY_CUTS = ((0.80, "critical"), (0.55, "high"), (0.35, "medium"), (0.15, "low"))
ALERT_MIN_SEVERITY = "medium"  # desde aquí se guarda la anomalía y se emite AnomalyDetected


@dataclass(frozen=True)
class Assessment:
    risk: float
    health_score: int
    severity: str
    top_factors: list[dict]  # schema Factor: variable, z_score, direction
    status: str  # MachineStatus


def _z_risk(z: float) -> float:
    return max(0.0, min(1.0, (abs(z) - Z_START) / Z_SPAN))


def _combine(risks: list[float]) -> float:
    remaining = 1.0
    for r in risks:
        remaining *= 1.0 - r
    return 1.0 - remaining


def _severity(risk: float, hits: list[RuleHit]) -> str:
    severity = next((s for cut, s in SEVERITY_CUTS if risk >= cut), "info")
    crit_hits = sum(1 for h in hits if h.level == CRIT)
    floor = "critical" if crit_hits >= 2 else "high" if crit_hits == 1 else "info"
    return max(severity, floor, key=SEVERITY_ORDER.index)


def is_alert(severity: str) -> bool:
    return SEVERITY_ORDER.index(severity) >= SEVERITY_ORDER.index(ALERT_MIN_SEVERITY)


def _status(reading_state: str, severity: str) -> str:
    if reading_state == "maintenance":
        return "maintenance"
    if severity == "critical":
        return "needs_intervention"
    if reading_state == "stopped":
        return "stopped"
    return "operational"


def top_factors(z_own: dict[str, float], z_cohort: dict[str, float], hits: list[RuleHit], limit: int = 3) -> list[dict]:
    """Variables que más explican la anomalía. Usa el z propio y, si es mayor, el de la cohorte."""
    strongest = {v: max(z_own.get(v, 0.0), z_cohort.get(v, 0.0), key=abs) for v in set(z_own) | set(z_cohort)}
    # Una regla disparada sin z-score (warm-up) igual debe explicar la alerta.
    for hit in hits:
        if abs(strongest.get(hit.variable, 0.0)) < Z_START:
            strongest[hit.variable] = Z_START if hit.direction == "high" else -Z_START
    ranked = sorted((item for item in strongest.items() if item[1] != 0.0), key=lambda kv: abs(kv[1]), reverse=True)
    return [{"variable": v, "z_score": round(z, 2), "direction": "high" if z > 0 else "low"} for v, z in ranked[:limit]]


def assess(
    reading: dict,
    hits: list[RuleHit],
    z_own: dict[str, float],
    z_cohort: dict[str, float],
    ml_risk: float | None,
) -> Assessment:
    rule_risk = max((RULE_RISK[h.level] for h in hits), default=0.0)
    # El riesgo estadístico combina todas las variables: varias desviaciones moderadas pesan juntas.
    stat_risk = _combine([max(_z_risk(z_own.get(v, 0.0)), _z_risk(z_cohort.get(v, 0.0))) for v in z_own])
    risk = _combine([rule_risk, stat_risk, ml_risk or 0.0])
    severity = _severity(risk, hits)
    return Assessment(
        risk=round(risk, 4),
        health_score=round(100 * (1 - risk)),
        severity=severity,
        top_factors=top_factors(z_own, z_cohort, hits),
        status=_status(reading.get("state", "operating"), severity),
    )
