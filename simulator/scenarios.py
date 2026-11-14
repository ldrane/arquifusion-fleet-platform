"""Escenarios inyectables del simulador (requerimientos §5.6, RF-02, RF-07, RF-08, RF-09, RF-12).

Los objetivos por defecto salen de la flota del seed (hallazgos #1 y #27): `degradacion` ataca EX-023
(CAT-336, norte; la demo del golden path, diagnóstico CMP-014) y los demás escenarios eligen máquinas
deterministas que existen en el seed y respetan su zona.

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


def pressure_spike(hours: float) -> Effect:
    """Pico de presión hidráulica (válvula de control irregular). Especialidad `hidraulica`."""
    return Effect(mul={"pressure_bar": 1.22}, add={"temperature_c": 5.0}, label="presion")


def electrical_fault(hours: float) -> Effect:
    """Falla eléctrica intermitente (alternador): caída de RPM. Especialidad `electrica`."""
    return Effect(mul={"rpm": 0.78}, add={"temperature_c": 4.0}, label="electrico")


def tire_vibration(hours: float) -> Effect:
    """Vibración por neumático desbalanceado: más vibración, menos velocidad. Especialidad `neumaticos`."""
    return Effect(mul={"vibration_mm_s": 1.9, "speed_kmh": 0.7}, label="neumaticos")


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


DEMO_MACHINE_ID = "EX-023"  # máquina del golden path (seed, OpenAPI y fixtures)
GROUP_ZONE = "norte"
GROUP_SIZE = 6


def _machine(machine_id: str) -> Callable[[list[MachineSpec]], list[MachineSpec]]:
    return lambda fleet: [m for m in fleet if m.machine_id == machine_id]


def _first(machine_types: tuple[str, ...], zone: str | None = None) -> Callable[[list[MachineSpec]], list[MachineSpec]]:
    """Primera máquina (por ID) de esos tipos y, si se indica, de esa zona; nunca la de la demo."""

    def pick(fleet: list[MachineSpec]) -> list[MachineSpec]:
        return [
            m
            for m in fleet
            if m.machine_type in machine_types and (zone is None or m.zone == zone) and m.machine_id != DEMO_MACHINE_ID
        ][:1]

    return pick


def _zone(zone: str) -> Callable[[list[MachineSpec]], list[MachineSpec]]:
    """Hasta GROUP_SIZE máquinas de una misma zona del seed (sin la de la demo, que tiene su propio incidente)."""
    return lambda fleet: [m for m in fleet if m.zone == zone and m.machine_id != DEMO_MACHINE_ID][:GROUP_SIZE]


def _idle_or_overused(spec: MachineSpec, hours: float) -> Effect:
    # Determinista: IDs pares quedan ociosas, impares sobreexplotadas.
    return idle(hours) if spec.number % 2 == 0 else overused(hours)


def _first_n_loaders(fleet: list[MachineSpec]) -> list[MachineSpec]:
    return [m for m in fleet if m.machine_type == "loader"][:4]


SCENARIOS: dict[str, Scenario] = {
    s.name: s
    for s in (
        Scenario("normal", "Operación normal, sin anomalías", lambda spec, h: NO_EFFECT, lambda fleet: []),
        Scenario(
            "degradacion",
            "Temperatura, vibración y combustible suben progresivamente",
            lambda spec, h: degradation(h),
            _machine(DEMO_MACHINE_ID),
        ),
        Scenario(
            "falla_subita",
            "Salto brusco de temperatura y vibración",
            lambda spec, h: sudden_failure(h),
            _first(("mining_truck",), "sur"),
        ),
        Scenario(
            "combustible",
            "Consumo de combustible anómalo con carga normal",
            lambda spec, h: fuel_anomaly(h),
            _first(("bulldozer",), "este"),
        ),
        Scenario(
            "grupal_zona",
            "Combustible contaminado en varias máquinas de una zona",
            lambda spec, h: contaminated_fuel(h),
            _zone(GROUP_ZONE),
        ),
        Scenario(
            "presion",
            "Pico de presión hidráulica",
            lambda spec, h: pressure_spike(h),
            _first(("excavator", "loader", "bulldozer", "drill"), "sur"),
        ),
        Scenario(
            "electrico",
            "Falla eléctrica intermitente: caída de RPM",
            lambda spec, h: electrical_fault(h),
            _first(("loader",), "oeste"),
        ),
        Scenario(
            "neumaticos",
            "Vibración por neumático en camión",
            lambda spec, h: tire_vibration(h),
            _first(("mining_truck",), "oeste"),
        ),
        Scenario(
            "ociosa",
            "Máquinas ociosas (IDs pares) y sobreexplotadas (IDs impares)",
            _idle_or_overused,
            _first_n_loaders,
        ),
    )
}
