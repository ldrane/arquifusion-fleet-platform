"""Tests del simulador serverless (TAREA-07) con dependencias inyectadas (sin AWS)."""

from datetime import UTC, datetime

import pytest
import service

NOW = datetime(2026, 11, 15, 15, 0, 10, tzinfo=UTC)


def state(**overrides) -> dict:
    base = {
        "enabled": True,
        "scenario": "falla_subita",
        "machines": ["CM-004"],
        "zone": None,
        "speedup": 240,
        "interval_s": 10,
        "started_at": "2026-11-15T15:00:00Z",
        "expires_at": "2026-11-15T15:20:00Z",
        "requested_by": "u-mant-01",
    }
    return {**base, **overrides}


def deps(current: dict, *, remaining: int = 60_000, now=NOW) -> dict:
    sent: list[list[dict]] = []
    put: list[dict] = []
    return {
        "get_state": lambda: current,
        "put_state": put.append,
        "send": sent.append,
        "now": lambda: now,
        "sleep": lambda _s: None,
        "remaining_ms": lambda: remaining,
        "sent": sent,
        "put": put,
    }


def test_disabled_does_nothing():
    d = deps(state(enabled=False))
    assert service.run(d) == {"skipped": "disabled"}
    assert d["sent"] == [] and d["put"] == []


def test_expired_disables_state():
    d = deps(state(expires_at="2026-11-15T15:00:00Z"))
    assert service.run(d) == {"skipped": "expired"}
    assert d["put"][0]["enabled"] is False and d["sent"] == []


def test_enabled_sends_full_fleet_and_marks_target():
    d = deps(state())
    out = service.run(d)
    assert out["ticks"] == 5 and out["scenario"] == "falla_subita" and out["targets"] == ["CM-004"]
    assert len(d["sent"]) == 5 and all(len(batch) == 100 for batch in d["sent"])
    marked = [r for batch in d["sent"] for r in batch if r["machine_id"] == "CM-004"]
    assert marked and all(r["sim_scenario"] == "falla_subita" for r in marked)
    others = [r for batch in d["sent"] for r in batch if r["machine_id"] != "CM-004"]
    assert all(r["sim_scenario"] is None for r in others)


def test_short_remaining_time_stops_the_loop():
    d = deps(state(), remaining=7_000)
    assert service.run(d) == {"ticks": 0, "readings": 0, "scenario": "falla_subita", "targets": ["CM-004"]}
    assert d["sent"] == []


def test_unknown_scenario_raises():
    with pytest.raises(ValueError):
        service.run(deps(state(scenario="inventado")))


def test_resolve_targets_raises_without_matches():
    from dataclasses import replace

    from simulator.fleet import build_fleet
    from simulator.scenarios import SCENARIOS

    empty = replace(SCENARIOS["falla_subita"], default_targets=lambda _fleet: [])
    with pytest.raises(ValueError):
        service.resolve_targets(build_fleet(), empty, ["NO-EXISTE"], None)
