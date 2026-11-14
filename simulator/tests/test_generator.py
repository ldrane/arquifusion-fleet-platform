from datetime import UTC, datetime, timedelta

import numpy as np

from simulator.generator import FleetSimulator, make_reading
from simulator.scenarios import NO_EFFECT, SCENARIOS
from simulator.tests.contract import validate

T0 = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)


def _run(fleet, scenario="normal", targets=(), ticks=3, seed=1):
    sim = FleetSimulator(fleet, SCENARIOS[scenario].effect, set(targets), started_at=T0, seed=seed)
    return [sim.tick(T0 + timedelta(minutes=i)) for i in range(ticks)]


def test_all_readings_valid_against_openapi(fleet, schemas):
    for name in SCENARIOS:
        targets = [m.machine_id for m in SCENARIOS[name].default_targets(fleet)]
        for tick in _run(fleet, name, targets, ticks=2):
            for reading in tick:
                validate(reading, schemas["TelemetryReading"], schemas)


def test_every_state_is_valid(fleet, schemas):
    rng = np.random.default_rng(0)
    for state in ("operating", "idle", "stopped", "maintenance"):
        validate(make_reading(fleet[0], T0, 100.0, state, NO_EFFECT, rng), schemas["TelemetryReading"], schemas)


def test_same_seed_same_readings(fleet):
    assert _run(fleet, seed=3) == _run(fleet, seed=3)
    assert _run(fleet, seed=3) != _run(fleet, seed=4)


def test_operating_hours_never_decrease(fleet):
    ticks = _run(fleet, ticks=5)
    for i in range(len(fleet)):
        hours = [t[i]["operating_hours"] for t in ticks]
        assert hours == sorted(hours)


def test_normal_scenario_has_no_labels(fleet):
    assert all(r["sim_scenario"] is None for t in _run(fleet) for r in t)
