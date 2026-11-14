"""Ayudas de prueba para las Lambdas de analítica (no se empaqueta en las Lambdas)."""

from datetime import date, timedelta

import boto3


class FakeAthena:
    """Simula `get_query_results` devolviendo filas ya tipadas como VarCharValue."""

    def __init__(self, rows: list[dict]):
        self.rows = rows

    def get_paginator(self, _name):
        return self

    def paginate(self, **_kw):
        columns = list(self.rows[0]) if self.rows else ["machine_id"]
        meta = {"ColumnInfo": [{"Name": c, "Type": _type(self.rows, c)} for c in columns]}
        header = {"Data": [{"VarCharValue": c} for c in columns]}
        body = [
            {"Data": [{"VarCharValue": str(r[c])} if r.get(c) is not None else {} for c in columns]} for r in self.rows
        ]
        yield {"ResultSet": {"ResultSetMetadata": meta, "Rows": [header, *body]}}


def _type(rows, column) -> str:
    sample = next((r[column] for r in rows if r.get(column) is not None), "")
    if isinstance(sample, bool):
        return "boolean"
    if isinstance(sample, int):
        return "bigint"
    if isinstance(sample, float):
        return "double"
    return "varchar"


def daily_row(machine_id: str, day: date, machine_type="excavator", zone="norte", **overrides) -> dict:
    """Fila de daily_machine_stats con valores normales; `overrides` cambia lo necesario."""
    row = {
        "machine_id": machine_id,
        "machine_type": machine_type,
        "dt": day.isoformat(),
        "model": "EX-350",
        "zone": zone,
        "readings": 96,
        "operating_readings": 60,
        "idle_readings": 20,
        "avg_fuel_lph": 30.0,
        "avg_fuel_lph_operating": 32.0,
        "avg_load_pct": 70.0,
        "avg_rpm": 1700.0,
        "avg_temperature_c": 85.0,
        "min_hours": 1000.0,
        "max_hours": 1012.0,
    }
    row.update(overrides)
    return row


def series(machine_id: str, today: date, days: int, **kwargs) -> list[dict]:
    """`days` filas consecutivas que terminan en `today`, con horas acumuladas crecientes."""
    rows = []
    for i in range(days):
        day = today - timedelta(days=days - 1 - i)
        hours = 1000.0 + 12 * i
        values = {k: (v(i) if callable(v) else v) for k, v in kwargs.items()}
        rows.append(daily_row(machine_id, day, **{"min_hours": hours, "max_hours": hours + 12, **values}))
    return rows


def create_table(name: str, pk: str = "pk", sk: str | None = "sk"):
    keys = [{"AttributeName": pk, "KeyType": "HASH"}]
    attrs = [{"AttributeName": pk, "AttributeType": "S"}]
    if sk:
        keys.append({"AttributeName": sk, "KeyType": "RANGE"})
        attrs.append({"AttributeName": sk, "AttributeType": "S"})
    return boto3.resource("dynamodb", region_name="us-east-1").create_table(
        TableName=name, KeySchema=keys, AttributeDefinitions=attrs, BillingMode="PAY_PER_REQUEST"
    )
