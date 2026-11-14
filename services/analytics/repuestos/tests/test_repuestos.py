from datetime import date, timedelta

import service
from analytics_common import records
from analytics_common.run_context import parse_event
from analytics_testkit import FakeAthena, create_table, series
from moto import mock_aws

TODAY = date(2026, 11, 14)
RANK_FIELDS = {"component_id", "name", "units_used_90d", "irregular_consumption"}
FORECAST_FIELDS = {
    "warehouse_id",
    "component_id",
    "expected_demand",
    "stock",
    "recommended_min",
    "recommended_max",
    "shortage_for_planned_maintenance",
}


def recs():
    steady = [
        records.Record("EX-1", "preventivo", TODAY - timedelta(days=7 * w), 1000.0, {"CMP-1": 2}, 100.0)
        for w in range(12)
    ]
    burst = [records.Record("EX-2", "correctivo", TODAY - timedelta(days=3), None, {"CMP-9": 10}, 900.0)]
    return steady + burst


def test_ranking_and_irregular_consumption():
    history = service.demand_history(recs(), TODAY)
    rows = service.ranking(history, {"CMP-1": "Filtro de aceite"})
    assert all(set(r) == RANK_FIELDS for r in rows)
    assert [(r["component_id"], r["units_used_90d"]) for r in rows] == [("CMP-1", 24), ("CMP-9", 10)]
    assert rows[0]["name"] == "Filtro de aceite" and rows[0]["irregular_consumption"] is False
    assert rows[1]["irregular_consumption"] is True


def test_forecast_by_warehouse_and_planned_shortage():
    inventory = [
        {"location_id": "WH-01", "component_id": "CMP-1", "stock": 1, "zone": "norte"},
        {"location_id": "WH-02", "component_id": "CMP-1", "stock": 50, "zone": "sur"},
    ]
    machines = [
        {"machine_id": "EX-1", "type": "excavator", "zone": "norte", "health_score": 30},
        {"machine_id": "EX-2", "type": "excavator", "zone": "sur", "health_score": 90},
    ]
    history = service.demand_history(recs(), TODAY)
    mix = service.component_mix(recs(), {"EX-1": "excavator", "EX-2": "excavator"})
    rows = service.forecast(30, history, mix, machines, inventory, {}, {"norte": 3, "sur": 1}, TODAY)
    by_key = {(r["warehouse_id"], r["component_id"]): r for r in rows}

    assert all(set(r) == FORECAST_FIELDS for r in rows)
    north, south = by_key[("WH-01", "CMP-1")], by_key[("WH-02", "CMP-1")]
    assert north["expected_demand"] > south["expected_demand"]  # 3 de 4 máquinas en el norte + EX-1 en riesgo
    assert north["shortage_for_planned_maintenance"] is True and south["shortage_for_planned_maintenance"] is False
    assert north["recommended_max"] > north["recommended_min"] >= 1


def test_run_writes_ranking_and_three_horizons():
    with mock_aws():
        t = {n: create_table(n) for n in ("machines", "insights")}
        t["records"] = create_table("records", pk="record_id", sk=None)
        t["inventory"] = create_table("inventory", pk="location_id", sk="component_id")
        t["catalog"] = create_table("catalog", pk="component_id", sk="sk")
        t["records"].put_item(
            Item={"record_id": "R1", "machine_id": "EX-1", "performed_at": "2026-11-10", "components": ["CMP-1"]}
        )
        t["inventory"].put_item(Item={"location_id": "WH-01", "component_id": "CMP-1", "stock": 3})
        t["catalog"].put_item(Item={"component_id": "CMP-1", "sk": "META", "name": "Filtro", "lead_time_days": 5})
        ctx = parse_event({"query_execution_id": "q", "correlation_id": "cid", "run_at": "2026-11-14T10:00:00Z"})

        out = service.run(
            ctx,
            FakeAthena(series("EX-1", TODAY, 7)),
            t["machines"],
            t["records"],
            t["inventory"],
            t["catalog"],
            t["insights"],
        )

        assert out["kind"] == "parts"
        kinds = {i["pk"] for i in t["insights"].scan()["Items"]}
        assert kinds == {"parts_ranking", "parts_forecast#7", "parts_forecast#30", "parts_forecast#90"}
        ranking = t["insights"].get_item(Key={"pk": "parts_ranking", "sk": "LATEST"})["Item"]["data"]
        assert ranking[0]["name"] == "Filtro"
