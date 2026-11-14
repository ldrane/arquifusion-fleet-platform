"""Flota simulada cargada desde los seeds de la Persona C (RF-01, requerimientos §5.6, hallazgo #1).

La verdad de la flota son `contracts/fixtures/seed/machines.json` y `machine_models.json` (seed v2,
generados por `scripts/seed_data.py`). El simulador NO inventa máquinas: usa los mismos IDs, modelo,
tipo, zona, coordenadas base, horómetro y `expected_interval_s`. El baseline de cada variable es el
`nominal` [media, desviación] del modelo (catalog `MODEL#<model>`, contratos.md §9).
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parents[1] / "contracts" / "fixtures" / "seed"
SEED_DIR_ENV = "SIMULATOR_SEED_DIR"  # override opcional (por ejemplo, seeds exportados en otra ruta)

ZONES: tuple[str, ...] = ("norte", "sur", "este", "oeste")
MACHINE_TYPES: tuple[str, ...] = ("excavator", "mining_truck", "loader", "bulldozer", "drill")

# Cuánto se desplaza cada tipo alrededor de su punto base (grados). El radio de una zona del seed es 0.012°.
ROAMING_DEG: dict[str, float] = {
    "excavator": 0.0008,
    "mining_truck": 0.0060,
    "loader": 0.0015,
    "bulldozer": 0.0010,
    "drill": 0.0002,
}
DEFAULT_EXPECTED_INTERVAL_S = 60  # contratos.md §3 (heartbeat: silencio a 3x)


@dataclass(frozen=True)
class Baseline:
    """Media y desviación estándar de una variable en operación normal (`nominal` del modelo)."""

    mean: float
    sd: float


@dataclass(frozen=True)
class MachineSpec:
    """Una máquina concreta de la flota (= ítem de `machines` del seed)."""

    machine_id: str
    machine_type: str
    model: str
    zone: str
    home_lat: float
    home_lon: float
    initial_operating_hours: float
    expected_interval_s: int = DEFAULT_EXPECTED_INTERVAL_S
    baselines: dict[str, Baseline] = field(default_factory=dict, hash=False)

    @property
    def roaming_deg(self) -> float:
        return ROAMING_DEG.get(self.machine_type, 0.001)

    @property
    def number(self) -> int:
        return int(self.machine_id.split("-")[1])


def _seed_dir(seed_dir: Path | str | None) -> Path:
    return Path(seed_dir or os.environ.get(SEED_DIR_ENV) or SEED_DIR)


def load_models(seed_dir: Path | str | None = None) -> dict[str, dict]:
    """Modelos del seed (`machine_models.json`) indexados por `model_id`."""
    models = json.loads((_seed_dir(seed_dir) / "machine_models.json").read_text())
    return {m["model_id"]: m for m in models}


def build_fleet(seed_dir: Path | str | None = None) -> list[MachineSpec]:
    """Flota completa del seed (100 máquinas, 5 tipos, 4 zonas), ordenada por `machine_id`."""
    base = _seed_dir(seed_dir)
    models = load_models(base)
    machines = json.loads((base / "machines.json").read_text())
    fleet = []
    for m in machines:
        model = models[m["model"]]
        home = m.get("home_location") or m["location"]
        fleet.append(
            MachineSpec(
                machine_id=m["machine_id"],
                machine_type=m["type"],
                model=m["model"],
                zone=m["zone"],
                home_lat=float(home["lat"]),
                home_lon=float(home["lon"]),
                initial_operating_hours=float(m["operating_hours"]),
                expected_interval_s=int(m.get("expected_interval_s") or DEFAULT_EXPECTED_INTERVAL_S),
                baselines={v: Baseline(float(mu), float(sd)) for v, (mu, sd) in model["nominal"].items()},
            )
        )
    return sorted(fleet, key=lambda s: s.machine_id)


def select(
    fleet: list[MachineSpec], machine_ids: list[str] | None = None, zone: str | None = None
) -> list[MachineSpec]:
    """Filtra la flota por IDs y/o zona. Sin filtros devuelve una lista vacía."""
    if not machine_ids and not zone:
        return []
    ids = set(machine_ids or [])
    return [m for m in fleet if (not ids or m.machine_id in ids) and (not zone or m.zone == zone)]


def to_dict(spec: MachineSpec) -> dict:
    """Vista exportable de una máquina (subconjunto de `Machine` del OpenAPI)."""
    return {
        "machine_id": spec.machine_id,
        "type": spec.machine_type,
        "model": spec.model,
        "location": {"lat": spec.home_lat, "lon": spec.home_lon, "zone": spec.zone},
        "operating_hours": spec.initial_operating_hours,
        "expected_interval_s": spec.expected_interval_s,
    }
