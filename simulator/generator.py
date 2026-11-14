"""Generación de lecturas TelemetryReading válidas según contracts/openapi.yaml (RF-01).

Las funciones son puras dado el `rng`: misma semilla = mismas lecturas.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone

import numpy as np

from simulator.fleet import MachineSpec
from simulator.scenarios import NO_EFFECT, Effect, EffectFn

# Rangos válidos de TelemetryReading (contracts/openapi.yaml).
RANGES: dict[str, tuple[float, float]] = {
    "temperature_c": (-20, 250),
    "vibration_mm_s": (0, 100),
    "pressure_bar": (0, 1000),
    "fuel_rate_lph": (0, 500),
    "load_pct": (0, 150),
    "speed_kmh": (0, 120),
    "rpm": (0, 4000),
}
VARIABLES = tuple(RANGES)

AMBIENT_TEMPERATURE_C = 18.0
IDLE_PROBABILITY = 0.08
LIMA = timezone(timedelta(hours=-5))
SHIFT_HOURS = range(6, 22)  # turno de 06:00 a 22:00 hora de Lima
NOMINAL_MAX_Z = 2.5  # la operación nominal queda dentro de μ±2.5σ (umbral de la capa 1: μ±3σ)
FUEL_LOAD_CORR = 0.6  # correlación consumo-carga en operación normal


def iso(ts: datetime) -> str:
    """Fecha ISO 8601 UTC con sufijo Z, como espera la API."""
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def on_shift(ts: datetime) -> bool:
    return ts.astimezone(LIMA).hour in SHIFT_HOURS


def base_state(ts: datetime, rng: np.random.Generator, shifts: bool) -> str:
    """Estado sin escenario: fuera de turno detenida; en turno operando o, a veces, en espera (idle)."""
    if shifts and not on_shift(ts):
        return "stopped"
    return "idle" if rng.random() < IDLE_PROBABILITY else "operating"


def _z(rng: np.random.Generator) -> float:
    """Ruido normal estándar truncado a ±NOMINAL_MAX_Z: una máquina sana no cruza el umbral μ±3σ (#2)."""
    return float(np.clip(rng.normal(0, 1), -NOMINAL_MAX_Z, NOMINAL_MAX_Z))


def normal_values(spec: MachineSpec, state: str, rng: np.random.Generator) -> dict[str, float]:
    """Valores normales según el `nominal` del modelo (seed) y el estado de la máquina."""
    b = spec.baselines
    if state in ("stopped", "maintenance"):
        return {
            "temperature_c": AMBIENT_TEMPERATURE_C + rng.normal(0, 2),
            "vibration_mm_s": 0.0,
            "pressure_bar": 0.0,
            "fuel_rate_lph": 0.0,
            "load_pct": 0.0,
            "speed_kmh": 0.0,
            "rpm": 0.0,
        }
    z = {v: _z(rng) for v in VARIABLES}
    # El consumo acompaña a la carga (fuel_per_load estable) sin cambiar su distribución marginal nominal.
    z["fuel_rate_lph"] = float(
        np.clip(FUEL_LOAD_CORR * z["load_pct"] + np.sqrt(1 - FUEL_LOAD_CORR**2) * z["fuel_rate_lph"],
                -NOMINAL_MAX_Z, NOMINAL_MAX_Z)
    )
    values = {v: b[v].mean + z[v] * b[v].sd for v in VARIABLES}
    if state == "idle":
        values.update(
            load_pct=0.0,
            speed_kmh=0.0,
            rpm=rng.normal(750, 20),
            fuel_rate_lph=values["fuel_rate_lph"] * 0.25,
            vibration_mm_s=values["vibration_mm_s"] * 0.4,
            temperature_c=values["temperature_c"] - 10,
        )
    return values


def apply_effect(values: dict[str, float], effect: Effect) -> dict[str, float]:
    """Aplica un escenario (fijar, multiplicar, sumar) y recorta a los rangos del contrato."""
    out = dict(values)
    out.update(effect.set)
    for var, factor in effect.mul.items():
        out[var] *= factor
    for var, delta in effect.add.items():
        out[var] += delta
    return {var: round(float(np.clip(out[var], *RANGES[var])), 2) for var in VARIABLES}


def jitter_location(spec: MachineSpec, rng: np.random.Generator) -> dict:
    r = spec.roaming_deg
    return {
        "lat": round(spec.home_lat + rng.normal(0, r), 6),
        "lon": round(spec.home_lon + rng.normal(0, r), 6),
        "zone": spec.zone,
    }


def make_reading(
    spec: MachineSpec, ts: datetime, operating_hours: float, state: str, effect: Effect, rng: np.random.Generator
) -> dict:
    """Construye una TelemetryReading. El escenario solo actúa si la máquina está operando."""
    active = effect if state == "operating" else NO_EFFECT
    final_state = active.state or state
    values = apply_effect(normal_values(spec, state, rng), active)
    return {
        "machine_id": spec.machine_id,
        "model": spec.model,
        "type": spec.machine_type,
        "timestamp": iso(ts),
        "location": jitter_location(spec, rng),
        "operating_hours": round(operating_hours, 2),
        **values,
        "state": final_state,
        "sim_scenario": active.label,
    }


@dataclass
class FleetSimulator:
    """Simulador con estado (horas de operación) para el modo stream.

    `effect` se aplica a las máquinas de `targets`; el tiempo del escenario corre `speedup` veces más rápido.
    """

    fleet: list[MachineSpec]
    effect: EffectFn
    targets: set[str]
    started_at: datetime
    seed: int = 42
    speedup: float = 1.0
    shifts: bool = False
    _hours: dict[str, float] = field(init=False)
    _last_ts: datetime | None = field(init=False, default=None)
    _rng: np.random.Generator = field(init=False)

    def __post_init__(self) -> None:
        self._hours = {m.machine_id: m.initial_operating_hours for m in self.fleet}
        self._rng = np.random.default_rng(self.seed)

    def scenario_hours(self, ts: datetime) -> float:
        return (ts - self.started_at).total_seconds() / 3600 * self.speedup

    def tick(self, ts: datetime) -> list[dict]:
        """Genera una lectura por máquina en el instante `ts`."""
        elapsed_h = (ts - self._last_ts).total_seconds() / 3600 if self._last_ts else 0.0
        self._last_ts = ts
        hours = self.scenario_hours(ts)
        readings = []
        for spec in self.fleet:
            state = base_state(ts, self._rng, self.shifts)
            effect = self.effect(spec, hours) if spec.machine_id in self.targets else NO_EFFECT
            if state == "operating":
                self._hours[spec.machine_id] += elapsed_h
            readings.append(make_reading(spec, ts, self._hours[spec.machine_id], state, effect, self._rng))
        return readings
