from datetime import date

import pytest
import service
from analytics_common import daily
from analytics_common.run_context import parse_event
from analytics_testkit import FakeAthena, create_table, series
from moto import mock_aws

TODAY = date(2026, 11, 14)
KPI_FIELDS = {
    "availability_pct",
    "mtbf_hours",
    "mttr_hours",
    "open_incidents",
    "machines_at_risk",
    "fleet_utilization_pct",
    "fuel_cost_per_ton_usd",
    "value_protected_usd",
    "avg_downtime_h",
}
INCIDENTS = [
    {
        "incident_id": "INC-1",
        "status": "closed",
        "detected_at": "2026-11-12T10:00:00Z",
        "resolved_at": "2026-11-12T14:00:00Z",
        "closed_at": "2026-11-12T14:00:00Z",
        "downtime_minutes": 240,
        "downtime_h": 4,
        "value_protected_usd": 33000,
        "zone": "norte",
    },
    {"incident_id": "INC-2", "status": "assigned", "detected_at": "2026-11-13T08:00:00Z", "zone": "norte"},
]
MACHINES = [
    {"machine_id": "EX-1", "health_score": 40, "zone": "norte"},
    {"machine_id": "EX-2", "health_score": 90, "zone": "sur"},
]


def test_kpis():
    stats = daily.from_rows(series("EX-1", TODAY, 7) + series("EX-2", TODAY, 7))
    k = service.kpis(stats, INCIDENTS, MACHINES, TODAY, 7)
    assert set(k) == KPI_FIELDS
    assert k["mttr_hours"] == 4.0 and k["open_incidents"] == 1 and k["machines_at_risk"] == 1
    assert k["mtbf_hours"] == round(2 * 7 * 12 / 2, 1)
    assert k["availability_pct"] == round(100 * (1 - 4 / (2 * 7 * 24)), 2)
    assert k["fleet_utilization_pct"] == round(60 / 96 * 100, 1)
    assert k["fuel_cost_per_ton_usd"] == round(32 * 1.1 / (0.7 * 400), 3)
    assert k["value_protected_usd"] == 33000 and k["avg_downtime_h"] == 4.0


@pytest.fixture
def tables():
    with mock_aws():
        t = {n: create_table(n) for n in ("machines", "insights")}
        t["incidents"] = create_table("incidents")
        for m in MACHINES:
            t["machines"].put_item(Item={"pk": f"OP-01#{m['machine_id']}", "sk": "META", **m})
        for inc in INCIDENTS:
            t["incidents"].put_item(Item={"pk": inc["incident_id"], "sk": "META", **inc})
        t["incidents"].put_item(Item={"pk": "INC-1", "sk": "EVT#1", "type": "ack"})  # eventos: se ignoran
        yield t


def run(tables, invoke_ia):
    ctx = parse_event({"query_execution_id": "q", "correlation_id": "cid", "run_at": "2026-11-14T10:00:00Z"})
    rows = series("EX-1", TODAY, 30) + series("EX-2", TODAY, 30, zone="sur")
    return service.run(
        ctx,
        FakeAthena(rows),
        tables["machines"],
        tables["incidents"],
        tables["insights"],
        invoke_ia,
        branches=[{"kind": "fuel", "flagged_7d": 0}],
    )


def test_run_writes_kpis_and_ai_report(tables):
    calls = []

    def invoke(payload):
        calls.append(payload)
        return {"result": {"summary_text": "Flota estable."}, "prompt_version": "executive-report-v1"}

    out = run(tables, invoke)
    report = tables["insights"].get_item(Key={"pk": "report#daily", "sk": "LATEST"})["Item"]["data"]
    assert out["prompt_version"] == "executive-report-v1"
    assert set(report) == {"generated_at", "summary_text", "prompt_version", "figures"}
    assert report["summary_text"] == "Flota estable."
    assert calls[0]["task"] == "executive_report" and calls[0]["payload"]["figures"]["kpis_7d"]["open_incidents"] == 1
    for kind in ("kpis#7d", "kpis#30d"):
        assert set(tables["insights"].get_item(Key={"pk": kind, "sk": "LATEST"})["Item"]["data"]) == KPI_FIELDS
        for zone in ("norte", "sur"):
            item = tables["insights"].get_item(Key={"pk": kind, "sk": f"LATEST#{zone}"})["Item"]
            assert set(item["data"]) == KPI_FIELDS and item["zone"] == zone
            assert tables["insights"].get_item(Key={"pk": kind, "sk": f"2026-11-14#{zone}"}).get("Item")
    norte = tables["insights"].get_item(Key={"pk": "kpis#7d", "sk": "LATEST#norte"})["Item"]["data"]
    sur = tables["insights"].get_item(Key={"pk": "kpis#7d", "sk": "LATEST#sur"})["Item"]["data"]
    assert (norte["open_incidents"], norte["machines_at_risk"]) == (1, 1)
    assert (sur["open_incidents"], sur["machines_at_risk"]) == (0, 0)


def test_report_survives_ia_failure(tables):
    def broken(_payload):
        raise RuntimeError("timeout")

    out = run(tables, broken)
    report = tables["insights"].get_item(Key={"pk": "report#daily", "sk": "LATEST"})["Item"]["data"]
    assert out["prompt_version"] == service.FALLBACK_PROMPT_VERSION
    assert "disponibilidad" in report["summary_text"]
