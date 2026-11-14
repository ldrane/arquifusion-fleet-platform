"""Escenarios inyectables del simulador (requerimientos §5.6, RF-02, RF-07, RF-08, RF-09, RF-12).

Un escenario transforma la lectura normal de las máquinas afectadas. El efecto depende de las horas
transcurridas desde que empezó el escenario (ya multiplicadas por el `speedup` en modo stream).
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from simulator.fleet import MachineSpec

# Horas que tarda la degradación progresiva en llegar a su máximo (a velocidad real).
DEGRADATION_RAMP_HOURS = 48.0
FUEL_RAMP_HOURS = 24.0


@dataclass(frozen=True)
class Effect:
    """Cambio sobre una lectura: multiplicar, sumar o fijar variables, forzar estado y etiquetar."""

    mul: dict[str, float] = field(default_factory=dict)
    add: dict[str, float] = field(default_factory=dict)
    set: dict[str, float] = field(default_factory=dict)
    state: str | None = None
    label: str | None = None


NO_EFFECT = Effect()

EffectFn = Callable[[MachineSpec, float], Effect]


def _progress(hours: float, ramp_hours: float) -> float:
    return min(max(hours / ramp_hours, 0.0), 1.0) if ramp_hours > 0 else 1.0


def degradation(hours: float, ramp_hours: float = DEGRADATION_RAMP_HOURS) -> Effect:
    """Desgaste progresivo: temperatura, vibración y combustible suben juntos (dolor: falla anticipable)."""
    p = _progress(hours, ramp_hours)
    return Effect(
        add={"temperature_c": 28.0 * p},
        mul={"vibration_mm_s": 1.0 + 1.6 * p, "fuel_rate_lph": 1.0 + 0.30 * p, "pressure_bar": 1.0 - 0.10 * p},
        label="degradacion",
    )


def sudden_failure(hours: float) -> Effect:
    """Falla súbita: salto inmediato de temperatura y vibración con caída de presión."""
    return Effect(
        add={"temperature_c": 40.0},
        mul={"vibration_mm_s": 3.5, "pressure_bar": 0.55},
        label="falla_subita",
    )


def fuel_anomaly(hours: float, ramp_hours: float = FUEL_RAMP_HOURS) -> Effect:
    """Consumo de combustible anómalo y creciente con carga normal (RF-07)."""
    p = _progress(hours, ramp_hours)
    return Effect(mul={"fuel_rate_lph": 1.0 + 0.5 * p}, label="combustible")


def contaminated_fuel(hours: float) -> Effect:
    """Combustible contaminado en una zona: varias máquinas a la vez con el mismo patrón (RF-12)."""
    return Effect(
        mul={"fuel_rate_lph": 1.35, "rpm": 0.92, "vibration_mm_s": 1.3},
        add={"temperature_c": 10.0},
        label="grupal_zona",
    )


def idle(hours: float) -> Effect:
    """Máquina ociosa: encendida sin producir (RF-08)."""
    return Effect(
        set={"load_pct": 3.0, "speed_kmh": 0.0, "rpm": 750.0}, mul={"fuel_rate_lph": 0.25}, state="idle", label="ociosa"
    )


def overused(hours: float) -> Effect:
    """Máquina sobreexplotada: carga y RPM por encima de su capacidad habitual (RF-08)."""
    return Effect(
        mul={"load_pct": 1.7, "rpm": 1.18, "fuel_rate_lph": 1.25}, add={"temperature_c": 9.0}, label="sobreexplotada"
    )


@dataclass(frozen=True)
class Scenario:
    """Escenario del CLI: cómo afecta a una máquina y qué máquinas toma si no se indican."""

    name: str
    description: str
    effect: EffectFn
    default_targets: Callable[[list[MachineSpec]], list[MachineSpec]]


def _first_of_type(machine_type: str) -> Callable[[list[MachineSpec]], list[MachineSpec]]:
    return lambda fleet: [m for m in fleet if m.machine_type == machine_type][:1]


def _zone(zone: str) -> Callable[[list[MachineSpec]], list[MachineSpec]]:
    return lambda fleet: [m for m in fleet if m.zone == zone][:6]


def _idle_or_overused(spec: MachineSpec, hours: float) -> Effect:
    # Determinista: IDs pares quedan ociosas, impares sobreexplotadas.
    return idle(hours) if spec.number % 2 == 0 else overused(hours)


SCENARIOS: dict[str, Scenario] = {
    s.name: s
    for s in (
        Scenario("normal", "Operación normal, sin anomalías", lambda spec, h: NO_EFFECT, lambda fleet: []),
        Scenario(
            "degradacion",
            "Temperatura, vibración y combustible suben progresivamente",
            lambda spec, h: degradation(h),
            _first_of_type("excavator"),
        ),
        Scenario(
            "falla_subita",
            "Salto brusco de temperatura y vibración",
            lambda spec, h: sudden_failure(h),
            _first_of_type("mining_truck"),
        ),
        Scenario(
            "combustible",
            "Consumo de combustible anómalo con carga normal",
            lambda spec, h: fuel_anomaly(h),
            _first_of_type("bulldozer"),
        ),
        Scenario(
            "grupal_zona",
            "Combustible contaminado en varias máquinas de una zona",
            lambda spec, h: contaminated_fuel(h),
            _zone("norte"),
        ),
        Scenario(
            "ociosa",
            "Máquinas ociosas (IDs pares) y sobreexplotadas (IDs impares)",
            _idle_or_overused,
            lambda fleet: [m for m in fleet if m.machine_type == "loader"][:4],
        ),
    )
}
