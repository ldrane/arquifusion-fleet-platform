"""Heartbeat: marca silenciosas y emite MachineSilent una sola vez por silencio (OBS-09)."""

from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws
from service import Heartbeat, HeartbeatConfig

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


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
            ("EX-023", "2026-11-13T11:50:00Z", {}),  # 10 min sin datos → silenciosa
            ("CM-104", "2026-11-13T11:59:30Z", {}),  # al día
            ("DR-007", "2026-11-13T11:50:00Z", {"expected_interval_s": 600}),  # intervalo largo → al día
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
        t.put_item(Item={"pk": "OP-01#LD-001", "sk": "META", "machine_id": "LD-001"})  # sin lecturas aún
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
        "last_seen_at": "2026-11-13T11:50:00Z",
        "expected_interval_s": 60,
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
