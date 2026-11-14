"""Definición determinista de la flota simulada (RF-01, requerimientos §5.6).

La flota es la misma para una misma semilla: el simulador, el historial y los seeds de la Persona C
comparten así los mismos IDs, modelos, zonas y baselines.
"""

from dataclasses import dataclass

import numpy as np

# Centro de la mina ficticia "Mina Huaylla" (sur del Perú) y desplazamiento de cada zona (grados).
MINE_CENTER = (-14.4000, -71.9500)
ZONES: dict[str, tuple[float, float]] = {
    "norte": (0.0180, 0.0000),
    "sur": (-0.0180, 0.0000),
    "este": (0.0000, 0.0180),
    "oeste": (0.0000, -0.0180),
}


@dataclass(frozen=True)
class Baseline:
    """Media y desviación estándar de una variable en operación normal."""

    mean: float
    sd: float


@dataclass(frozen=True)
class MachineType:
    """Parámetros de un tipo de máquina (enum MachineType del OpenAPI)."""

    name: str
    prefix: str
    count: int
    models: tuple[str, ...]
    roaming_deg: float  # cuánto se desplaza alrededor de su punto base
    baselines: dict[str, Baseline]


def _b(**values: tuple[float, float]) -> dict[str, Baseline]:
    return {k: Baseline(*v) for k, v in values.items()}


MACHINE_TYPES: tuple[MachineType, ...] = (
    MachineType(
        "excavator",
        "EX",
        24,
        ("AF-EX350", "AF-EX520"),
        0.0008,
        _b(
            temperature_c=(85, 3),
            vibration_mm_s=(3.0, 0.35),
            pressure_bar=(220, 10),
            fuel_rate_lph=(32, 2),
            load_pct=(70, 8),
            speed_kmh=(3, 1),
            rpm=(1800, 60),
        ),
    ),
    MachineType(
        "mining_truck",
        "CM",
        25,
        ("AF-HT90", "AF-HT140"),
        0.0060,
        _b(
            temperature_c=(88, 3),
            vibration_mm_s=(2.5, 0.30),
            pressure_bar=(180, 8),
            fuel_rate_lph=(60, 4),
            load_pct=(80, 10),
            speed_kmh=(25, 5),
            rpm=(1700, 80),
        ),
    ),
    MachineType(
        "loader",
        "CF",
        12,
        ("AF-WL980", "AF-WL1200"),
        0.0015,
        _b(
            temperature_c=(84, 3),
            vibration_mm_s=(2.8, 0.30),
            pressure_bar=(200, 9),
            fuel_rate_lph=(28, 2),
            load_pct=(65, 9),
            speed_kmh=(10, 3),
            rpm=(1750, 70),
        ),
    ),
    MachineType(
        "bulldozer",
        "BD",
        10,
        ("AF-D85", "AF-D155"),
        0.0010,
        _b(
            temperature_c=(86, 3),
            vibration_mm_s=(3.5, 0.40),
            pressure_bar=(210, 10),
            fuel_rate_lph=(40, 3),
            load_pct=(75, 8),
            speed_kmh=(5, 1.5),
            rpm=(1850, 60),
        ),
    ),
    MachineType(
        "drill",
        "PF",
        13,
        ("AF-RD45", "AF-RD60"),
        0.0002,
        _b(
            temperature_c=(82, 3),
            vibration_mm_s=(4.0, 0.45),
            pressure_bar=(250, 12),
            fuel_rate_lph=(35, 2.5),
            load_pct=(60, 7),
            speed_kmh=(0.5, 0.3),
            rpm=(2000, 70),
        ),
    ),
)

TYPES_BY_NAME: dict[str, MachineType] = {t.name: t for t in MACHINE_TYPES}


@dataclass(frozen=True)
class MachineSpec:
    """Una máquina concreta de la flota."""

    machine_id: str
    machine_type: str
    model: str
    zone: str
    home_lat: float
    home_lon: float
    initial_operating_hours: float

    @property
    def type_spec(self) -> MachineType:
        return TYPES_BY_NAME[self.machine_type]

    @property
    def number(self) -> int:
        return int(self.machine_id.split("-")[1])


def build_fleet(seed: int = 42) -> list[MachineSpec]:
    """Construye la flota completa (84 máquinas, 5 tipos, 4 zonas). Mismo `seed` = misma flota."""
    rng = np.random.default_rng(seed)
    zone_names = list(ZONES)
    fleet = []
    for mtype in MACHINE_TYPES:
        for i in range(1, mtype.count + 1):
            zone = zone_names[(i - 1) % len(zone_names)]
            dlat, dlon = ZONES[zone]
            fleet.append(
                MachineSpec(
                    machine_id=f"{mtype.prefix}-{i:03d}",
                    machine_type=mtype.name,
                    model=mtype.models[(i - 1) % len(mtype.models)],
                    zone=zone,
                    home_lat=round(MINE_CENTER[0] + dlat + rng.normal(0, 0.004), 6),
                    home_lon=round(MINE_CENTER[1] + dlon + rng.normal(0, 0.004), 6),
                    initial_operating_hours=round(float(rng.uniform(2_000, 15_000)), 1),
                )
            )
    return fleet


def select(
    fleet: list[MachineSpec], machine_ids: list[str] | None = None, zone: str | None = None
) -> list[MachineSpec]:
    """Filtra la flota por IDs y/o zona. Sin filtros devuelve una lista vacía."""
    if not machine_ids and not zone:
        return []
    ids = set(machine_ids or [])
    return [m for m in fleet if (not ids or m.machine_id in ids) and (not zone or m.zone == zone)]


def to_dict(spec: MachineSpec) -> dict:
    """Vista exportable de una máquina (sirve a la Persona C para generar los seeds de `machines`)."""
    return {
        "machine_id": spec.machine_id,
        "type": spec.machine_type,
        "model": spec.model,
        "location": {"lat": spec.home_lat, "lon": spec.home_lon, "zone": spec.zone},
        "operating_hours": spec.initial_operating_hours,
    }
