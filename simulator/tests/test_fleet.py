import json
import re
from pathlib import Path

from simulator.fleet import MACHINE_TYPES, SEED_DIR, ZONES, build_fleet, select, to_dict

SEED_MACHINES = json.loads((Path(SEED_DIR) / "machines.json").read_text())


def test_fleet_size_types_and_zones(fleet):
    assert len(fleet) == 100
    assert {m.machine_type for m in fleet} == set(MACHINE_TYPES)
    assert {m.zone for m in fleet} == set(ZONES)


def test_fleet_matches_seed_exactly(fleet):
    """#1: IDs, modelo, tipo, zona, coordenadas, horómetro y expected_interval_s son los del seed."""
    by_id = {m.machine_id: m for m in fleet}
    assert set(by_id) == {m["machine_id"] for m in SEED_MACHINES}
    for seed in SEED_MACHINES:
        spec = by_id[seed["machine_id"]]
        assert (spec.model, spec.machine_type, spec.zone) == (seed["model"], seed["type"], seed["zone"])
        assert (spec.home_lat, spec.home_lon) == (seed["home_location"]["lat"], seed["home_location"]["lon"])
        assert spec.initial_operating_hours == seed["operating_hours"]
        assert spec.expected_interval_s == seed["expected_interval_s"] == 60
        assert spec.initial_status == seed["status"]


def test_baselines_are_model_nominal(fleet):
    models = {m["model_id"]: m for m in json.loads((Path(SEED_DIR) / "machine_models.json").read_text())}
    for spec in fleet:
        nominal = models[spec.model]["nominal"]
        assert {v: (b.mean, b.sd) for v, b in spec.baselines.items()} == {v: tuple(x) for v, x in nominal.items()}


def test_ids_are_unique_and_match_contract(fleet, schemas):
    pattern = schemas["TelemetryReading"]["properties"]["machine_id"]["pattern"]
    ids = [m.machine_id for m in fleet]
    assert len(ids) == len(set(ids))
    assert all(re.match(pattern, i) for i in ids)


def test_machine_types_match_openapi_enum(schemas):
    assert set(MACHINE_TYPES) == set(schemas["MachineType"]["enum"])


def test_fleet_is_deterministic():
    assert build_fleet() == build_fleet()


def test_select_by_machine_and_zone(fleet):
    assert [m.machine_id for m in select(fleet, ["EX-001"])] == ["EX-001"]
    assert all(m.zone == "norte" for m in select(fleet, zone="norte"))
    assert select(fleet) == []


def test_to_dict_is_machine_shaped(fleet):
    d = to_dict(fleet[0])
    assert set(d) == {"machine_id", "type", "model", "location", "operating_hours", "expected_interval_s", "status"}


def test_demo_machine_matches_golden_path(fleet):
    ex023 = next(m for m in fleet if m.machine_id == "EX-023")
    assert (ex023.model, ex023.zone) == ("CAT-336", "norte")


def test_fleet_uses_every_seed_model(fleet):
    """Seed v4: 19 modelos; cada uno existe como MODEL#<model> (catálogo) y tiene máquinas."""
    models = {m["model_id"] for m in json.loads((Path(SEED_DIR) / "machine_models.json").read_text())}
    assert {m.model for m in fleet} == models and len(models) >= 15


def test_parked_machines_report_their_seed_state(fleet):
    from datetime import UTC, datetime

    from simulator.generator import FleetSimulator
    from simulator.scenarios import NO_EFFECT

    parked = {m.machine_id: m.parked_state for m in fleet if m.parked_state}
    assert set(parked.values()) == {"maintenance", "stopped"}
    sim = FleetSimulator(fleet, lambda spec, h: NO_EFFECT, set(), started_at=datetime(2026, 11, 14, tzinfo=UTC))
    readings = {r["machine_id"]: r for r in sim.tick(datetime(2026, 11, 14, 15, tzinfo=UTC))}
    for mid, state in parked.items():
        assert readings[mid]["state"] == state and readings[mid]["rpm"] == 0.0
