"""Lógica del simulador serverless "gemelo de flota" (TAREA-07).

Sin AWS: el handler inyecta `get_state`, `put_state`, `send`, `now`, `sleep`, `remaining_ms` y `seed_dir`.
Reutiliza el mismo generador de telemetría que el simulador local (`simulator/`), pero solo importa los módulos
livianos (`fleet`, `scenarios`, `generator`, `sender`); NO importa `simulator.cli` ni `simulator.history`
(arrastran pandas/pyarrow y no caben en el presupuesto de arranque).

Estado (SSM String `/arquifusion/{stage}/sim/state`, JSON):
    {"enabled": true, "scenario": "falla_subita", "machines": ["CM-004"], "zone": null,
     "speedup": 240, "interval_s": 10, "started_at": "...", "expires_at": "...", "requested_by": "u-mant-01"}
"""

import math
import time
from datetime import UTC, datetime

from simulator.fleet import build_fleet, select
from simulator.generator import FleetSimulator
from simulator.scenarios import SCENARIOS

MIN_REMAINING_MS = 8000  # no se abre un tick si la Lambda ya va a morir
MAX_RUN_S = 50  # presupuesto de trabajo por invocación (timeout de la Lambda: 60 s)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def resolve_targets(fleet, scenario, machines, zone):
    """Misma regla que `simulator/cli.py::resolve_targets`, pero lanza ValueError en vez de SystemExit."""
    targets = select(fleet, machines, zone) or scenario.default_targets(fleet)
    if scenario.name != "normal" and not targets:
        raise ValueError("Ninguna máquina coincide con machines/zone")
    return targets


def run(deps: dict) -> dict:
    """Un tick-loop acotado. Devuelve un resumen o `{"skipped": ...}` si no corresponde trabajar."""
    state = deps["get_state"]() or {}
    if not state.get("enabled"):
        return {"skipped": "disabled"}

    now = deps["now"]
    current = now()
    expires_at = _parse(state.get("expires_at"))
    if expires_at and current > expires_at:
        deps["put_state"]({**state, "enabled": False})
        return {"skipped": "expired"}

    fleet = build_fleet(deps.get("seed_dir"))
    scenario = SCENARIOS.get(state.get("scenario"))
    if scenario is None:
        raise ValueError(f"escenario desconocido: {state.get('scenario')!r}")
    targets = resolve_targets(fleet, scenario, state.get("machines"), state.get("zone"))
    ids = {m.machine_id for m in targets}

    interval_s = max(1.0, float(state.get("interval_s") or 10))
    sim = FleetSimulator(
        fleet,
        scenario.effect,
        ids,
        started_at=_parse(state.get("started_at")) or current,
        seed=42,
        speedup=float(state.get("speedup") or 240),
    )
    max_ticks = max(1, math.floor(MAX_RUN_S / interval_s))
    ticks = 0
    readings = 0
    while deps["remaining_ms"]() > MIN_REMAINING_MS and ticks < max_ticks:
        started = time.monotonic()
        batch = sim.tick(now())
        deps["send"](batch)
        readings += len(batch)
        ticks += 1
        deps["sleep"](max(0.0, interval_s - (time.monotonic() - started)))
    return {
        "ticks": ticks,
        "readings": readings,
        "scenario": scenario.name,
        "targets": [m.machine_id for m in targets],
    }


def utc_now() -> datetime:
    """Reloj real (el handler lo inyecta; los tests usan uno fijo)."""
    return datetime.now(UTC)
