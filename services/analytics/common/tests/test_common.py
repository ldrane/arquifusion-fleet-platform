from datetime import date

import boto3
from analytics_common.athena import fetch_rows
from analytics_common.daily import by_machine, from_rows, linear_slope, median, weighted_avg, window
from analytics_common.insights_store import write_insight
from analytics_common.records import normalize
from analytics_common.run_context import parse_event
from moto import mock_aws


class FakeAthena:
    def __init__(self, pages):
        self.pages = pages

    def get_paginator(self, _name):
        return self

    def paginate(self, **_kw):
        return iter(self.pages)


def page(rows, header=True):
    meta = {
        "ColumnInfo": [
            {"Name": "machine_id", "Type": "varchar"},
            {"Name": "readings", "Type": "bigint"},
            {"Name": "avg_fuel_lph", "Type": "double"},
        ]
    }
    data = (
        [{"Data": [{"VarCharValue": "machine_id"}, {"VarCharValue": "readings"}, {"VarCharValue": "avg_fuel_lph"}]}]
        if header
        else []
    )
    data += [{"Data": [{"VarCharValue": v} if v is not None else {} for v in r]} for r in rows]
    return {"ResultSet": {"ResultSetMetadata": meta, "Rows": data}}


def test_fetch_rows_casts_and_skips_header_once():
    rows = fetch_rows(FakeAthena([page([("EX-1", "10", "30.5")]), page([("EX-2", "3", None)], header=False)]), "q")
    assert rows == [
        {"machine_id": "EX-1", "readings": 10, "avg_fuel_lph": 30.5},
        {"machine_id": "EX-2", "readings": 3, "avg_fuel_lph": None},
    ]


def stat(day, mid="EX-1", fuel=30.0, op=10):
    return {
        "machine_id": mid,
        "machine_type": "excavator",
        "dt": day,
        "readings": 12,
        "operating_readings": op,
        "idle_readings": 2,
        "avg_fuel_lph_operating": fuel,
        "min_hours": 100.0,
        "max_hours": 108.0,
    }


def test_daily_helpers():
    stats = from_rows([stat("2026-11-10"), stat("2026-11-13", fuel=40.0, op=30), stat("2026-10-01")])
    recent = window(stats, date(2026, 11, 13), 7)
    assert len(recent) == 2 and recent[0].hours_operated == 8.0
    assert weighted_avg(recent, "fuel_lph") == (30 * 10 + 40 * 30) / 40
    assert set(by_machine(stats)) == {"EX-1"}
    assert median([3, 1, 2, 4]) == 2.5
    assert round(linear_slope([(0, 1), (1, 2), (2, 3)]), 6) == 1.0


def test_records_accept_aliases():
    recs = normalize(
        [
            {"machine_id": "EX-1", "fecha": "2026-11-01", "tipo": "preventivo", "componentes": ["CMP-1", "CMP-1"]},
            {
                "machine_id": "EX-2",
                "performed_at": "2026-11-02T10:00:00Z",
                "components": [{"component_id": "CMP-2", "quantity": 3}],
                "cost_usd": 120,
            },
            {"machine_id": "EX-3"},  # sin fecha: se ignora
        ]
    )
    assert [r.components for r in recs] == [{"CMP-1": 2}, {"CMP-2": 3}]
    assert recs[0].kind == "preventivo" and recs[1].cost_usd == 120.0


def test_parse_event_uses_execution_start_time():
    ctx = parse_event({"query_execution_id": "q", "correlation_id": "c", "run_at": "2026-11-14T10:00:00.123Z"})
    assert ctx.today == date(2026, 11, 14) and ctx.run_at_iso == "2026-11-14T10:00:00Z"


def test_write_insight_writes_day_and_latest():
    with mock_aws():
        table = boto3.resource("dynamodb", region_name="us-east-1").create_table(
            TableName="insights",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        write_insight(table, "fuel#7d", [{"lph": 30.5}], "2026-11-14T10:00:00Z", "cid")
        keys = sorted(i["sk"] for i in table.scan()["Items"])
        assert keys == ["2026-11-14", "LATEST"]
