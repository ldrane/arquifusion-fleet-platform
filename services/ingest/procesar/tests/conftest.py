"""Fixtures de `procesar`: DynamoDB con moto, Firehose y EventBridge falsos, y generador de lecturas."""

import copy
import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
import pytest
from ingest_procesar.config import Settings
from ingest_procesar.repository import Repository
from ingest_procesar.rules import ThresholdProvider
from moto import mock_aws
from service import Processor  # import a nivel de módulo: ver CONTRIBUTING.md (Tests)

FIXTURES = Path(__file__).resolve().parents[4] / "contracts" / "fixtures"
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)

SETTINGS = Settings(
    stage="test",
    table_machines="t-machines",
    table_machine_state="t-machine-state",
    table_idempotency="t-idempotency",
    table_anomalies="t-anomalies",
    event_bus_name="t-fleet-events",
    firehose_stream="t-telemetry",
    model_bucket="t-artifacts",
    warmup_readings=5,
)


class FakeFirehose:
    def __init__(self, fail: bool = False):
        self.records: list[dict] = []
        self.fail = fail

    def put_record_batch(self, DeliveryStreamName, Records):
        if self.fail:
            return {
                "FailedPutCount": len(Records),
                "RequestResponses": [{"ErrorCode": "ServiceUnavailable"}] * len(Records),
            }
        self.records += [json.loads(r["Data"]) for r in Records]
        return {"FailedPutCount": 0, "RequestResponses": [{"RecordId": "x"}] * len(Records)}


class FakeEvents:
    def __init__(self):
        self.entries: list[dict] = []

    def put_events(self, Entries):
        self.entries += Entries
        return {"FailedEntryCount": 0, "Entries": [{"EventId": "e"}] * len(Entries)}


class NoModel:
    version = None

    def score(self, reading):
        return None


def _create_tables(ddb):
    for name, has_sk in (
        (SETTINGS.table_machines, True),
        (SETTINGS.table_machine_state, True),
        (SETTINGS.table_idempotency, False),
        (SETTINGS.table_anomalies, True),
    ):
        keys = [{"AttributeName": "pk", "KeyType": "HASH"}]
        attrs = [{"AttributeName": "pk", "AttributeType": "S"}]
        if has_sk:
            keys.append({"AttributeName": "sk", "KeyType": "RANGE"})
            attrs.append({"AttributeName": "sk", "AttributeType": "S"})
        ddb.create_table(TableName=name, KeySchema=keys, AttributeDefinitions=attrs, BillingMode="PAY_PER_REQUEST")


@pytest.fixture
def aws():
    """DynamoDB (moto) + Firehose y EventBridge falsos, listos para construir un Processor."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        _create_tables(ddb)
        firehose, events = FakeFirehose(), FakeEvents()
        repo = Repository(SETTINGS, ddb, firehose, events)
        yield {"ddb": ddb, "firehose": firehose, "events": events, "repo": repo}


@pytest.fixture
def thresholds():
    return ThresholdProvider(lambda machine_type: None)


@pytest.fixture
def base_reading() -> dict:
    return json.loads((FIXTURES / "api" / "telemetry_batch.json").read_text())["readings"][0]


def make_reading(base: dict, minutes: int, **overrides) -> dict:
    """Lectura normal con ruido pequeño, `minutes` después de NOW - 10 h."""
    rnd = random.Random(minutes)
    r = copy.deepcopy(base)
    r.update(
        timestamp=(NOW - timedelta(hours=10) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        temperature_c=85 + rnd.uniform(-1, 1),
        vibration_mm_s=4 + rnd.uniform(-0.2, 0.2),
        pressure_bar=210 + rnd.uniform(-3, 3),
        fuel_rate_lph=35 + rnd.uniform(-0.5, 0.5),
        rpm=1800 + rnd.uniform(-20, 20),
        state="operating",
        sim_scenario=None,
    )
    r.update(overrides)
    return r


def sqs_event(*batches: list[dict], bodies: list[str] | None = None) -> dict:
    records = [
        {
            "messageId": f"m{i}",
            "body": json.dumps({"correlation_id": f"cid-{i}", "received_at": "0", "batch": {"readings": b}}),
        }
        for i, b in enumerate(batches)
    ]
    records += [{"messageId": f"raw{i}", "body": body} for i, body in enumerate(bodies or [])]
    return {"Records": records}


@pytest.fixture
def reading(base_reading):
    """Fábrica de lecturas: `reading(minutes, **overrides)`."""
    return lambda minutes, **overrides: make_reading(base_reading, minutes, **overrides)


@pytest.fixture
def sqs():
    """Fábrica de eventos SQS: `sqs(batch1, batch2, bodies=[...])`."""
    return sqs_event


@pytest.fixture
def processor(aws, thresholds):
    """Processor con reloj fijo y sin modelo ML (capas 1 y 2)."""
    return Processor(SETTINGS, aws["repo"], thresholds, NoModel(), clock=lambda: NOW)


@pytest.fixture
def settings():
    return SETTINGS


@pytest.fixture
def no_model():
    return NoModel()


@pytest.fixture
def now():
    return NOW


@pytest.fixture
def fake_firehose():
    return FakeFirehose
