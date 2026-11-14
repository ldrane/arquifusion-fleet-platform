from datetime import date

import pytest
import service
from analytics_common import daily, records
from analytics_common.run_context import parse_event
from analytics_testkit import FakeAthena, create_table, series
from moto import mock_aws

TODAY = date(2026, 11, 14)
PLAN_FIELDS = {"machine_id", "zone", "next_maintenance_at", "priority", "flag", "reason"}


def stats(*rows_lists):
    return daily.from_rows([r for rows in rows_lists for r in rows])


def test_heavy_use_brings_maintenance_forward():
    light = stats(series("EX-1", TODAY, 30, avg_load_pct=60.0))
    heavy = stats(series("EX-2", TODAY, 30, avg_load_pct=95.0, avg_temperature_c=105.0))
    rec = lambda mid: records.Record(mid, "preventivo", date(2026, 10, 20), 1100.0, {}, 0.0)  # noqa: E731
    a = service.plan_machine({"machine_id": "EX-1", "type": "excavator"}, light, rec("EX-1"), TODAY)
    b = service.plan_machine({"machine_id": "EX-2", "type": "excavator"}, heavy, rec("EX-2"), TODAY)
    assert service.intensity(heavy) > service.intensity(light) == 1.0
    assert b.next_maintenance_at < a.next_maintenance_at


def test_flags():
    s = stats(series("EX-1", TODAY, 30))
    hours_now = s[-1].max_hours
    overdue = service.plan_machine(
        {"machine_id": "EX-1", "type": "excavator"},
        s,
        records.Record("EX-1", "preventivo", date(2026, 8, 1), hours_now - 600, {}, 0.0),
        TODAY,
    )
    sick = service.plan_machine({"machine_id": "EX-1", "type": "excavator", "health_score": 30}, s, None, TODAY)
    # calendario: último servicio hace 45 días (vence en 5), pero casi sin horas de uso
    idle = stats(series("EX-3", TODAY, 30, min_hours=2000.0, max_hours=2000.5))
    unnecessary = service.plan_machine(
        {"machine_id": "EX-3", "type": "excavator"},
        idle,
        records.Record("EX-3", "preventivo", date(2026, 9, 30), 1990.0, {}, 0.0),
        TODAY,
    )
    assert overdue.flag == "overdue" and "intervalo" in overdue.reason
    assert sick.flag == "overdue" and "Health" in sick.reason
    assert unnecessary.flag == "unnecessary"


def test_plan_shape_and_priority():
    plan = service.build_plan(
        [{"machine_id": "EX-1", "type": "excavator", "health_score": 30}, {"machine_id": "EX-2", "type": "excavator"}],
        stats(
            series("EX-1", TODAY, 10), series("EX-2", TODAY, 10), series("TR-9", TODAY, 10, machine_type="mining_truck")
        ),
        [],
        TODAY,
    )
    assert all(set(p) == PLAN_FIELDS for p in plan)
    assert [p["priority"] for p in plan] == [1, 2, 3]
    assert plan[0]["machine_id"] == "EX-1" and plan[0]["flag"] == "overdue"
    assert {p["machine_id"] for p in plan} == {"EX-1", "EX-2", "TR-9"}  # TR-9 solo existe en el lake


@pytest.fixture
def env():
    with mock_aws():
        yield {
            "machines": create_table("machines"),
            "records": create_table("records", pk="record_id", sk=None),
            "insights": create_table("insights"),
        }


def test_run_writes_insight_and_updates_machines(env):
    env["machines"].put_item(
        Item={"pk": "OP-01#EX-1", "sk": "META", "machine_id": "EX-1", "type": "excavator", "zone": "norte"}
    )
    env["records"].put_item(
        Item={
            "record_id": "R1",
            "machine_id": "EX-1",
            "type": "preventivo",
            "performed_at": "2026-10-20",
            "operating_hours": 1100,
        }
    )
    ctx = parse_event({"query_execution_id": "q", "correlation_id": "cid", "run_at": "2026-11-14T10:00:00Z"})

    out = service.run(ctx, FakeAthena(series("EX-1", TODAY, 30)), env["machines"], env["records"], env["insights"])

    assert out["kind"] == "maintenance_plan" and out["machines"] == 1
    latest = env["insights"].get_item(Key={"pk": "maintenance_plan", "sk": "LATEST"})["Item"]
    assert latest["data"][0]["machine_id"] == "EX-1" and latest["correlation_id"] == "cid"
    machine = env["machines"].get_item(Key={"pk": "OP-01#EX-1", "sk": "META"})["Item"]
    assert machine["next_maintenance_at"] == latest["data"][0]["next_maintenance_at"]
