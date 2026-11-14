from datetime import date

import service
from analytics_common import daily, fleet
from analytics_common.run_context import parse_event
from analytics_testkit import FakeAthena, create_table, series
from moto import mock_aws

TODAY = date(2026, 11, 14)
FUEL_FIELDS = {
    "machine_id",
    "zone",
    "lph",
    "l_per_ton",
    "vs_peers_pct",
    "vs_own_history_pct",
    "progressive_increase",
    "probable_causes",
}


def fleet_rows():
    normal = [r for mid in ("EX-1", "EX-2", "EX-3") for r in series(mid, TODAY, 90)]
    # EX-9 consume cada día un poco más durante los últimos 30 días y con RPM altas
    rising = series(
        "EX-9", TODAY, 90, avg_fuel_lph_operating=lambda i: 32.0 if i < 60 else 32.0 + (i - 60) * 0.6, avg_rpm=2000.0
    )
    return normal + rising


def test_detects_progressive_increase_and_deviation():
    rows = service.analyze(daily.from_rows(fleet_rows()), TODAY, 7)
    by_id = {r["machine_id"]: r for r in rows}
    assert all(set(r) == FUEL_FIELDS for r in rows)
    assert rows[0]["machine_id"] == "EX-9"
    worst = by_id["EX-9"]
    assert worst["progressive_increase"] is True
    assert worst["vs_peers_pct"] > 15 and worst["vs_own_history_pct"] > 10
    assert "Operación a RPM elevadas (estilo de manejo)" in worst["probable_causes"]
    assert by_id["EX-1"]["probable_causes"] == [] and by_id["EX-1"]["vs_peers_pct"] == 0.0
    assert by_id["EX-1"]["l_per_ton"] == round(32.0 / (0.7 * 400), 3)


def test_run_writes_both_periods():
    with mock_aws():
        insights = create_table("insights")
        ctx = parse_event({"query_execution_id": "q", "correlation_id": "cid", "run_at": "2026-11-14T10:00:00Z"})
        out = service.run(ctx, FakeAthena(fleet_rows()), insights)
        assert out == {"kind": "fuel", "flagged_7d": 1}
        for kind in ("fuel#7d", "fuel#30d"):
            assert insights.get_item(Key={"pk": kind, "sk": "LATEST"})["Item"]["data"]


def test_peers_are_same_model_or_catalog_nominal():
    """#13: un KOM-PC2000 (110 L/h nominal) no se marca por consumir más que un CAT-336 (38 L/h)."""
    cat = [r for mid in ("EX-1", "EX-2", "EX-3") for r in series(mid, TODAY, 30, model="CAT-336", avg_fuel_lph_operating=38.0)]
    kom = series("EX-4", TODAY, 30, model="KOM-PC2000", avg_fuel_lph_operating=112.0)
    catalog = fleet.Catalog.from_items(
        [
            {"pk": "MODEL#KOM-PC2000", "model_id": "KOM-PC2000", "type": "excavator", "payload_t": 12.0,
             "nominal": {"fuel_rate_lph": [110, 8], "rpm": [1800, 80]}},
            {"pk": "MODEL#CAT-336", "model_id": "CAT-336", "type": "excavator", "payload_t": 2.5,
             "nominal": {"fuel_rate_lph": [38, 4], "rpm": [1800, 80]}},
        ]
    )
    rows = {r["machine_id"]: r for r in service.analyze(daily.from_rows(cat + kom), TODAY, 7, catalog)}
    assert rows["EX-4"]["vs_peers_pct"] == round((112 / 110 - 1) * 100, 1) and rows["EX-4"]["probable_causes"] == []
    assert rows["EX-1"]["vs_peers_pct"] == 0.0
    assert rows["EX-4"]["l_per_ton"] == round(112.0 / (0.7 * 12.0 * fleet.CYCLES_PER_HOUR["excavator"]), 3)
