"""Heartbeat: marca silenciosas y emite MachineSilent una sola vez por silencio (OBS-09)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import boto3
import pytest
from moto import mock_aws
from service import Heartbeat, HeartbeatConfig

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
FIXTURE = Path(__file__).resolve().parents[4] / "contracts" / "fixtures" / "events" / "machine_silent.json"


@pytest.fixture
def table():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        t = ddb.create_table(
            TableName="t-machines",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        for machine_id, last_seen, extra in (
            ("EX-023", "2026-11-13T11:50:00Z", {"zone": "norte", "expected_interval_s": 60}),  # 10 min → silenciosa
            ("CM-004", "2026-11-13T11:59:30Z", {"zone": "sur", "expected_interval_s": 60}),  # al día
            ("PF-007", "2026-11-13T11:50:00Z", {"zone": "oeste", "expected_interval_s": 600}),  # intervalo largo
        ):
            t.put_item(
                Item={
                    "pk": f"OP-01#{machine_id}",
                    "sk": "META",
                    "machine_id": machine_id,
                    "last_seen_at": last_seen,
                    "status": "operational",
                    **extra,
                }
            )
        t.put_item(Item={"pk": "OP-01#CF-001", "sk": "META", "machine_id": "CF-001"})  # sin lecturas aún
        yield t


def test_marks_and_emits_once(table):
    sent = []
    hb = Heartbeat(table, sent.append, HeartbeatConfig(), clock=lambda: NOW)

    first, second = hb.run(), hb.run()
    assert (first["candidates"], first["silenced"], first["storm"]) == (1, 1, False)
    assert (second["candidates"], second["silenced"]) == (0, 0)  # ya silenciosa: no reemite

    assert len(sent) == 1
    detail = sent[0]
    assert detail["version"] == 1 and detail["data"] == {
        "machine_id": "EX-023",
        "zone": "norte",
        "last_seen_at": "2026-11-13T11:50:00Z",
        "expected_interval_s": 60,
        "silence_threshold_s": 180,
    }
    item = table.get_item(Key={"pk": "OP-01#EX-023", "sk": "META"})["Item"]
    assert item["status"] == "silent" and item["status_before_silent"] == "operational"


def test_new_reading_after_scan_prevents_marking(table):
    hb = Heartbeat(table, lambda d: None, HeartbeatConfig(), clock=lambda: NOW)
    machine = {"pk": "OP-01#EX-023", "sk": "META", "machine_id": "EX-023", "last_seen_at": "2026-11-13T11:00:00Z"}
    assert hb._mark_silent(machine, NOW) is False  # last_seen_at cambió: condición falla


def test_publish_failure_restores_status(table):
    def boom(detail):
        raise RuntimeError("EventBridge caído")

    with pytest.raises(RuntimeError):
        Heartbeat(table, boom, HeartbeatConfig(), clock=lambda: NOW).run()
    assert table.get_item(Key={"pk": "OP-01#EX-023", "sk": "META"})["Item"]["status"] == "operational"


def test_detail_matches_contract_fixture(table):
    sent = []
    Heartbeat(table, sent.append, HeartbeatConfig(), clock=lambda: NOW).run()
    expected = json.loads(json.loads(FIXTURE.read_text())[0]["Detail"])
    assert set(sent[0]) == set(expected)
    assert set(sent[0]["data"]) == set(expected["data"])


def _fleet(table, n_silent, n_ok):
    for i in range(n_silent):
        table.put_item(
            Item={
                "pk": f"OP-01#S-{i:03}",
                "sk": "META",
                "machine_id": f"S-{i:03}",
                "last_seen_at": "2026-11-13T11:40:00Z",
                "status": "operational",
                "zone": "norte",
            }
        )
    for i in range(n_ok):
        table.put_item(
            Item={
                "pk": f"OP-01#K-{i:03}",
                "sk": "META",
                "machine_id": f"K-{i:03}",
                "last_seen_at": "2026-11-13T11:59:50Z",
                "status": "operational",
                "zone": "sur",
            }
        )


def test_mass_silence_is_ingest_outage_marks_without_incidents(table):
    """Se detuvo el simulador: 90+ máquinas callan a la vez -> sin MachineSilent (no tormenta de Lambdas)."""
    _fleet(table, n_silent=90, n_ok=5)
    sent = []
    result = Heartbeat(table, sent.append, HeartbeatConfig(), clock=lambda: NOW).run()
    assert result["storm"] is True and result["storm_suppressed"] == 91 and result["silenced"] == 0
    assert sent == []
    item = table.get_item(Key={"pk": "OP-01#S-000", "sk": "META"})["Item"]
    assert item["status"] == "silent"  # el mapa sí lo refleja


def test_events_per_run_are_capped(table):
    """Fuera de tormenta (pocas máquinas sobre una flota grande) se emiten como máximo 5 por corrida."""
    _fleet(table, n_silent=7, n_ok=60)  # 8 candidatas de 70 activas (< 20 %): no es tormenta
    sent = []
    hb = Heartbeat(table, sent.append, HeartbeatConfig(), clock=lambda: NOW)
    first = hb.run()
    assert first["storm"] is False and first["silenced"] == 5 and len(sent) == 5
    second = hb.run()
    assert second["silenced"] == 3 and len(sent) == 8  # el resto, en el ciclo siguiente
