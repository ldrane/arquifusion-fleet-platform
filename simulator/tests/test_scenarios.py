from datetime import UTC, datetime

import numpy as np
import pytest

from simulator.generator import make_reading
from simulator.scenarios import NO_EFFECT, SCENARIOS, degradation

T0 = datetime(2026, 11, 13, 15, 0, tzinfo=UTC)
N = 400


def _mean(spec, effect, var):
    rng = np.random.default_rng(0)
    return np.mean([make_reading(spec, T0, 1.0, "operating", effect, rng)[var] for _ in range(N)])


def _sd(spec, var):
    return spec.baselines[var].sd


@pytest.mark.parametrize(
    "scenario, hours, var, min_sigmas",
    [
        ("degradacion", 48, "temperature_c", 5),
        ("degradacion", 48, "vibration_mm_s", 5),
        ("degradacion", 48, "fuel_rate_lph", 2.5),
        ("falla_subita", 0, "temperature_c", 8),
        ("falla_subita", 0, "vibration_mm_s", 8),
        ("combustible", 24, "fuel_rate_lph", 5),
        ("grupal_zona", 0, "fuel_rate_lph", 3),
        ("presion", 0, "pressure_bar", 3),
        ("neumaticos", 0, "vibration_mm_s", 3),
    ],
)
def test_scenario_raises_variable(fleet, scenario, hours, var, min_sigmas):
    spec = SCENARIOS[scenario].default_targets(fleet)[0]
    effect = SCENARIOS[scenario].effect(spec, hours)
    assert _mean(spec, effect, var) - _mean(spec, NO_EFFECT, var) > min_sigmas * _sd(spec, var)
    assert effect.label == scenario


def test_electrical_fault_drops_rpm(fleet):
    spec = SCENARIOS["electrico"].default_targets(fleet)[0]
    effect = SCENARIOS["electrico"].effect(spec, 0)
    assert _mean(spec, NO_EFFECT, "rpm") - _mean(spec, effect, "rpm") > 3 * _sd(spec, "rpm")


def test_default_targets_exist_in_seed_and_respect_zone(fleet):
    by_id = {m.machine_id: m for m in fleet}
    assert [m.machine_id for m in SCENARIOS["degradacion"].default_targets(fleet)] == ["EX-023"]
    for name, scenario in SCENARIOS.items():
        for m in scenario.default_targets(fleet):
            assert by_id[m.machine_id] == m, name
    assert all(m.machine_id != "EX-023" for m in SCENARIOS["grupal_zona"].default_targets(fleet))
    # seed v4: los escenarios por defecto solo toman máquinas operativas (no en taller ni en reserva)
    for name, scenario in SCENARIOS.items():
        assert all(m.parked_state is None for m in scenario.default_targets(fleet)), name


def test_degradation_is_progressive():
    temps = [degradation(h).add["temperature_c"] for h in (0, 12, 24, 48, 96)]
    assert temps == sorted(temps) and temps[0] == 0 and temps[-1] == temps[-2]


def test_fuel_scenario_keeps_normal_load(fleet):
    spec = SCENARIOS["combustible"].default_targets(fleet)[0]
    effect = SCENARIOS["combustible"].effect(spec, 24)
    assert abs(_mean(spec, effect, "load_pct") - _mean(spec, NO_EFFECT, "load_pct")) < _sd(spec, "load_pct")


def test_group_scenario_hits_several_machines_of_one_zone(fleet):
    targets = SCENARIOS["grupal_zona"].default_targets(fleet)
    assert len(targets) >= 3 and len({m.zone for m in targets}) == 1


def test_idle_and_overused(fleet):
    targets = SCENARIOS["ociosa"].default_targets(fleet)
    rng = np.random.default_rng(0)
    readings = {
        m.machine_id: make_reading(m, T0, 1.0, "operating", SCENARIOS["ociosa"].effect(m, 0), rng) for m in targets
    }
    idle = [r for r in readings.values() if r["sim_scenario"] == "ociosa"]
    over = [r for r in readings.values() if r["sim_scenario"] == "sobreexplotada"]
    assert idle and over
    assert all(r["state"] == "idle" and r["load_pct"] < 10 for r in idle)
    assert all(r["load_pct"] > 90 for r in over)
