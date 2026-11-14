from datetime import date

import service
from analytics_common import daily, records
from analytics_common.run_context import parse_event
from analytics_testkit import FakeAthena, create_table, series
from moto import mock_aws

TODAY = date(2026, 11, 14)
FIELDS = {
    "machine_id",
    "zone",
    "utilization_pct",
    "classification",
    "cost_per_hour_usd",
    "quadrant",
    "redistribution_suggestion",
}
QUADRANTS = {"high_prod_low_cost", "high_prod_high_cost", "low_prod_low_cost", "low_prod_high_cost"}


def fleet_rows():
    return (
        series("EX-1", TODAY, 30, zone="norte", operating_readings=20, readings=96)  # ~21 % → underused
        + series("EX-2", TODAY, 30, zone="sur", operating_readings=90, readings=96, min_hours=0.0, max_hours=20.0)
        + series("EX-3", TODAY, 30, zone="sur")
    )


def test_classification_matrix_and_redistribution():
    recs = [records.Record("EX-3", "correctivo", date(2026, 11, 10), None, {}, 5000.0)]
    rows = service.analyze(daily.from_rows(fleet_rows()), recs, TODAY, 7)
    by_id = {r["machine_id"]: r for r in rows}
    assert all(set(r) == FIELDS and r["quadrant"] in QUADRANTS for r in rows)
    assert by_id["EX-1"]["classification"] == "underused"
    assert by_id["EX-2"]["classification"] == "overused"
    assert by_id["EX-3"]["classification"] == "normal"
    assert "zona sur" in by_id["EX-1"]["redistribution_suggestion"]
    assert "EX-1" in by_id["EX-2"]["redistribution_suggestion"]
    assert by_id["EX-3"]["cost_per_hour_usd"] > by_id["EX-1"]["cost_per_hour_usd"]  # incluye costo de mantenimiento
    assert by_id["EX-3"]["redistribution_suggestion"] is None


def test_run_writes_both_periods():
    with mock_aws():
        insights = create_table("insights")
        recs = create_table("records", pk="record_id", sk=None)
        ctx = parse_event({"query_execution_id": "q", "correlation_id": "cid", "run_at": "2026-11-14T10:00:00Z"})
        out = service.run(ctx, FakeAthena(fleet_rows()), recs, insights)
        assert out == {"kind": "productivity", "underused_7d": 1, "overused_7d": 1}
        assert insights.get_item(Key={"pk": "productivity#30d", "sk": "LATEST"})["Item"]["data"]
