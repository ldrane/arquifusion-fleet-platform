import re

from simulator.fleet import MACHINE_TYPES, ZONES, build_fleet, select, to_dict


def test_fleet_size_types_and_zones(fleet):
    assert 60 <= len(fleet) <= 100
    assert {m.machine_type for m in fleet} == {t.name for t in MACHINE_TYPES}
    assert {m.zone for m in fleet} == set(ZONES)


def test_ids_are_unique_and_match_contract(fleet, schemas):
    pattern = schemas["TelemetryReading"]["properties"]["machine_id"]["pattern"]
    ids = [m.machine_id for m in fleet]
    assert len(ids) == len(set(ids))
    assert all(re.match(pattern, i) for i in ids)


def test_machine_types_match_openapi_enum(schemas):
    assert {t.name for t in MACHINE_TYPES} == set(schemas["MachineType"]["enum"])


def test_fleet_is_deterministic():
    assert build_fleet(7) == build_fleet(7)
    assert build_fleet(7) != build_fleet(8)


def test_select_by_machine_and_zone(fleet):
    assert [m.machine_id for m in select(fleet, ["EX-001"])] == ["EX-001"]
    assert all(m.zone == "norte" for m in select(fleet, zone="norte"))
    assert select(fleet) == []


def test_to_dict_is_machine_shaped(fleet):
    d = to_dict(fleet[0])
    assert set(d) == {"machine_id", "type", "model", "location", "operating_hours"}


def test_demo_machine_from_contract_fixtures_exists(fleet):
    assert "EX-023" in {m.machine_id for m in fleet}
