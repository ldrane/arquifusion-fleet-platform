"""Historial sintético con fallas etiquetadas para entrenar y validar el modelo (requerimientos §5.6, RF-13).

Escribe Parquet con el esquema EXACTO del data lake (`arquifusion_ml.lake`), particionado igual que Firehose:
`<out>/telemetry/operation_id=.../dt=.../machine_type=.../part-00000.parquet`.

Cada falla tiene un periodo precursor etiquetado (`sim_scenario`) que termina en `failure_at`; así `retrain`
puede medir la anticipación (`mean_lead_time_hours`). Las fallas se guardan también en
`<out>/labels/failures.parquet` como verdad de referencia.
"""

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from arquifusion_ml.lake import LAKE_COLUMNS, flatten_reading, partition_prefix

from simulator.fleet import ZONES, MachineSpec
from simulator.generator import base_state, make_reading
from simulator.scenarios import (
    NO_EFFECT,
    Effect,
    contaminated_fuel,
    degradation,
    fuel_anomaly,
    idle,
    overused,
    sudden_failure,
)

FAILURES_FILE = "labels/failures.parquet"

# Duración del periodo precursor (horas, rango uniforme) por tipo de falla.
PRECURSOR_HOURS: dict[str, tuple[float, float]] = {
    "degradacion": (24, 72),
    "combustible": (12, 48),
    "falla_subita": (0.5, 2),
}
FAILURE_KIND_WEIGHTS: dict[str, float] = {"degradacion": 0.5, "combustible": 0.3, "falla_subita": 0.2}
REPAIR_HOURS = (8, 24)
ZONE_EVENT_HOURS = 12
ZONE_EVENT_MACHINES = 6
FAILURES_PER_MACHINE_90D = 1.0
ZONE_EVENTS_90D = 2
PROFILE_MACHINES = 3  # máquinas con utilización crónicamente baja y otras tantas sobreexplotadas

_GLUE_TO_ARROW = {
    "string": pa.string(),
    "double": pa.float64(),
    "int": pa.int32(),
    "timestamp": pa.timestamp("ms", tz="UTC"),
}
LAKE_SCHEMA = pa.schema([(name, _GLUE_TO_ARROW[glue_type]) for name, glue_type in LAKE_COLUMNS])


@dataclass(frozen=True)
class FailureEvent:
    """Falla etiquetada: precursor [precursor_start, failure_at) y reparación [failure_at, repair_end)."""

    machine_id: str
    machine_type: str
    zone: str
    kind: str
    precursor_start: datetime
    failure_at: datetime
    repair_end: datetime

    def overlaps(self, other: "FailureEvent") -> bool:
        return self.precursor_start < other.repair_end and other.precursor_start < self.repair_end

    def effect_at(self, ts: datetime) -> Effect:
        hours = (ts - self.precursor_start).total_seconds() / 3600
        ramp = (self.failure_at - self.precursor_start).total_seconds() / 3600
        match self.kind:
            case "degradacion":
                return degradation(hours, ramp)
            case "combustible":
                return fuel_anomaly(hours, ramp)
            case "falla_subita":
                return sudden_failure(hours)
            case "grupal_zona":
                return contaminated_fuel(hours)
        raise ValueError(f"tipo de falla desconocido: {self.kind}")


def _hours(h: float) -> timedelta:
    return timedelta(hours=float(h))


def _add_if_free(events: list[FailureEvent], new: FailureEvent) -> None:
    if not any(new.overlaps(e) for e in events if e.machine_id == new.machine_id):
        events.append(new)


def schedule_failures(
    fleet: list[MachineSpec], start: datetime, end: datetime, rng: np.random.Generator
) -> list[FailureEvent]:
    """Programa fallas individuales (Poisson por máquina) y eventos grupales por zona, sin solapes."""
    days = (end - start).total_seconds() / 86_400
    kinds = list(FAILURE_KIND_WEIGHTS)
    weights = np.array(list(FAILURE_KIND_WEIGHTS.values()))
    events: list[FailureEvent] = []
    for spec in fleet:
        for _ in range(rng.poisson(FAILURES_PER_MACHINE_90D * days / 90)):
            kind = str(rng.choice(kinds, p=weights / weights.sum()))
            precursor = _hours(rng.uniform(*PRECURSOR_HOURS[kind]))
            failure_at = start + precursor + (end - start - precursor) * rng.uniform(0.0, 0.95)
            _add_if_free(
                events,
                FailureEvent(
                    spec.machine_id,
                    spec.machine_type,
                    spec.zone,
                    kind,
                    failure_at - precursor,
                    failure_at,
                    failure_at + _hours(rng.uniform(*REPAIR_HOURS)),
                ),
            )
    for _ in range(round(ZONE_EVENTS_90D * days / 90)):
        zone = str(rng.choice(list(ZONES)))
        begin = start + (end - start - _hours(ZONE_EVENT_HOURS)) * rng.uniform(0.0, 1.0)
        for spec in [m for m in fleet if m.zone == zone][:ZONE_EVENT_MACHINES]:
            _add_if_free(
                events,
                FailureEvent(
                    spec.machine_id,
                    spec.machine_type,
                    zone,
                    "grupal_zona",
                    begin,
                    begin + _hours(ZONE_EVENT_HOURS),
                    begin + _hours(ZONE_EVENT_HOURS),
                ),
            )
    return sorted(events, key=lambda e: (e.precursor_start, e.machine_id))


def utilization_profiles(fleet: list[MachineSpec], rng: np.random.Generator) -> dict[str, Effect]:
    """Máquinas crónicamente ociosas o sobreexplotadas (RF-08). Sin etiqueta: no son fallas."""
    chosen = rng.choice(len(fleet), size=2 * PROFILE_MACHINES, replace=False)
    profiles = {}
    for n, idx in enumerate(chosen):
        base = idle(0) if n < PROFILE_MACHINES else overused(0)
        profiles[fleet[idx].machine_id] = replace(base, label=None)
    return profiles


def _state_and_effect(
    spec: MachineSpec, ts: datetime, events: list[FailureEvent], profile: Effect, rng: np.random.Generator
) -> tuple[str, Effect]:
    state = base_state(ts, rng, shifts=True)
    for event in events:
        if event.precursor_start <= ts < event.failure_at:
            return state, event.effect_at(ts)
        if event.failure_at <= ts < event.repair_end:
            return "maintenance", NO_EFFECT
    return state, profile


def generate_day(
    fleet: list[MachineSpec],
    day: datetime,
    interval_min: int,
    events_by_machine: dict[str, list[FailureEvent]],
    profiles: dict[str, Effect],
    operating_hours: dict[str, float],
    rng: np.random.Generator,
) -> list[dict]:
    """Lecturas de un día completo en formato API. Actualiza `operating_hours` in situ."""
    step = timedelta(minutes=interval_min)
    readings = []
    for i in range(int(timedelta(days=1) / step)):
        ts = day + i * step
        for spec in fleet:
            state, effect = _state_and_effect(
                spec, ts, events_by_machine.get(spec.machine_id, []), profiles.get(spec.machine_id, NO_EFFECT), rng
            )
            reading = make_reading(spec, ts, operating_hours[spec.machine_id], state, effect, rng)
            if reading["state"] == "operating":
                operating_hours[spec.machine_id] += step.total_seconds() / 3600
            readings.append(reading)
    return readings


def to_lake_frame(readings: list[dict]) -> pd.DataFrame:
    """Aplana lecturas al esquema del lake y agrega la columna de partición machine_type."""
    df = pd.DataFrame([flatten_reading(r) for r in readings], columns=[c for c, _ in LAKE_COLUMNS])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["machine_type"] = [r["type"] for r in readings]
    return df


def write_partitions(df: pd.DataFrame, out_dir: Path, operation_id: str, dt: str) -> list[Path]:
    """Escribe un Parquet por machine_type para el día `dt`."""
    written = []
    for machine_type, part in df.groupby("machine_type"):
        path = out_dir / partition_prefix(operation_id, dt, str(machine_type)) / "part-00000.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(part.drop(columns="machine_type"), schema=LAKE_SCHEMA, preserve_index=False)
        pq.write_table(table, path)
        written.append(path)
    return written


def write_failures(events: list[FailureEvent], out_dir: Path) -> Path:
    path = out_dir / FAILURES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([asdict(e) for e in events]).to_parquet(path, index=False)
    return path


def generate_history(
    fleet: list[MachineSpec],
    days: int,
    out_dir: Path,
    *,
    interval_min: int = 15,
    seed: int = 42,
    operation_id: str = "OP-01",
    end: datetime | None = None,
) -> dict:
    """Genera `days` días de historial terminando en `end` (por defecto hoy 00:00 UTC). Devuelve un resumen."""
    end = end or datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days)
    rng = np.random.default_rng(seed)
    events = schedule_failures(fleet, start, end, rng)
    profiles = utilization_profiles(fleet, rng)
    events_by_machine: dict[str, list[FailureEvent]] = defaultdict(list)
    for e in events:
        events_by_machine[e.machine_id].append(e)
    operating_hours = {m.machine_id: m.initial_operating_hours for m in fleet}

    rows = 0
    for d in range(days):
        day = start + timedelta(days=d)
        readings = generate_day(
            fleet, day, interval_min, events_by_machine, profiles, operating_hours, np.random.default_rng([seed, d])
        )
        write_partitions(to_lake_frame(readings), out_dir, operation_id, day.strftime("%Y-%m-%d"))
        rows += len(readings)
    write_failures(events, out_dir)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "machines": len(fleet),
        "rows": rows,
        "failures": len(events),
        "failures_by_kind": dict(Counter(e.kind for e in events)),
        "out_dir": str(out_dir),
    }


def upload(out_dir: Path, s3_uri: str) -> int:
    """Sube el historial a S3 conservando las rutas (`s3://bucket/prefijo`). Devuelve los archivos subidos."""
    import boto3  # solo se necesita al subir

    if not s3_uri.startswith("s3://"):
        raise ValueError("El destino debe ser s3://bucket[/prefijo]")
    bucket, _, prefix = s3_uri[5:].partition("/")
    s3 = boto3.client("s3")
    files = [p for p in out_dir.rglob("*.parquet") if p.is_file()]
    for path in files:
        key = "/".join(filter(None, [prefix.strip("/"), path.relative_to(out_dir).as_posix()]))
        s3.upload_file(str(path), bucket, key)
    return len(files)
