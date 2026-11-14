"""Heartbeat: marca silenciosas y emite MachineSilent una sola vez por silencio (OBS-09)."""

from datetime import UTC, datetime

import json
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

    assert hb.run() == {"candidates": 1, "silenced": 1}
    assert hb.run() == {"candidates": 0, "silenced": 0}  # ya silenciosa: no reemite

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
