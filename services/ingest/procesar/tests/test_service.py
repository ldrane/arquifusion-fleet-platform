"""Flujo completo de `procesar` sobre DynamoDB (moto): idempotencia, estado, dedup y fallas (RF-02, RNF-07)."""

import json

from service import Processor


def _warm_up(processor, reading, sqs, n=10):
    processor.handle(sqs([reading(i) for i in range(n)]))


def _degraded(reading, minute):
    return reading(minute, temperature_c=104.0, vibration_mm_s=9.5, fuel_rate_lph=58.0)


def _event_details(events):
    return [json.loads(e["Detail"]) for e in events.entries if e["DetailType"] == "AnomalyDetected"]


def test_normal_batch_updates_state_and_lake(processor, aws, reading, sqs, settings):
    result = processor.handle(sqs([reading(i) for i in range(3)]))

    assert result == {"batchItemFailures": []}
    machine = aws["ddb"].Table(settings.table_machines).get_item(Key={"pk": "OP-01#EX-023", "sk": "META"})["Item"]
    assert machine["status"] == "operational" and machine["severity"] == "info"
    assert machine["last_seen_at"] == reading(2)["timestamp"]
    state = aws["ddb"].Table(settings.table_machine_state)
    assert state.get_item(Key={"pk": "EX-023", "sk": "BASELINE"})["Item"]["stats"]["temperature_c"]["n"] == 3
    agg = state.get_item(Key={"pk": "EX-023", "sk": "AGG#1h#2026-11-13T02"})["Item"]
    assert agg["count"] == 3 and agg["vars"]["rpm"]["min"] <= agg["vars"]["rpm"]["avg"] <= agg["vars"]["rpm"]["max"]
    rows = aws["firehose"].records
    assert len(rows) == 3
    assert (
        rows[0]["operation_id"] == "OP-01" and rows[0]["dt"] == "2026-11-13" and rows[0]["machine_type"] == "excavator"
    )
    assert rows[0]["correlation_id"] == "cid-0" and rows[0]["zone"] == "norte"
    assert not aws["events"].entries


def test_duplicate_readings_are_processed_once(processor, aws, reading, sqs):
    batch = [reading(i) for i in range(3)]
    processor.handle(sqs(batch))
    processor.handle(sqs(batch))
    assert len(aws["firehose"].records) == 3


def test_degradation_emits_one_anomaly_event(processor, aws, reading, sqs, settings):
    _warm_up(processor, reading, sqs)
    processor.handle(sqs([_degraded(reading, 20), _degraded(reading, 21)]))
    processor.handle(sqs([_degraded(reading, 22)]))  # misma anomalía, otro lote: bloqueo vigente

    details = _event_details(aws["events"])
    assert len(details) == 1
    detail = details[0]
    assert detail["version"] == 1 and detail["correlation_id"] == "cid-0"
    data = detail["data"]
    assert data["machine_id"] == "EX-023" and data["zone"] == "norte"
    assert data["severity"] in ("medium", "high", "critical")
    assert {f["variable"] for f in data["top_factors"]} >= {"temperature_c", "vibration_mm_s"}
    assert data["model_version"] == "baseline-only"
    anomalies = aws["ddb"].Table(settings.table_anomalies).scan()["Items"]
    assert len(anomalies) == 3 and anomalies[0]["gsi1pk"] == "norte#2026-11-13"


def test_open_incident_blocks_anomaly_event(processor, aws, reading, sqs, settings):
    _warm_up(processor, reading, sqs)
    aws["ddb"].Table(settings.table_machines).update_item(
        Key={"pk": "OP-01#EX-023", "sk": "META"},
        UpdateExpression="SET open_incident_id = :i",
        ExpressionAttributeValues={":i": "INC-1"},
    )
    processor.handle(sqs([_degraded(reading, 20)]))
    assert _event_details(aws["events"]) == []


def test_alerts_do_not_feed_the_baseline(processor, aws, reading, sqs, settings):
    _warm_up(processor, reading, sqs)
    processor.handle(sqs([_degraded(reading, 20)]))
    stats = (
        aws["ddb"].Table(settings.table_machine_state).get_item(Key={"pk": "EX-023", "sk": "BASELINE"})["Item"]["stats"]
    )
    assert stats["temperature_c"]["n"] == 10


def test_invalid_message_reported_without_blocking_others(processor, aws, reading, sqs):
    result = processor.handle(sqs([reading(0)], bodies=["no es json"]))
    assert result == {"batchItemFailures": [{"itemIdentifier": "raw0"}]}
    assert len(aws["firehose"].records) == 1


def test_failed_message_releases_idempotency(aws, thresholds, reading, sqs, settings, no_model, now, fake_firehose):
    from ingest_procesar.repository import Repository

    failing = Repository(settings, aws["ddb"], fake_firehose(fail=True), aws["events"])
    result = Processor(settings, failing, thresholds, no_model, clock=lambda: now).handle(sqs([reading(0)]))

    assert result == {"batchItemFailures": [{"itemIdentifier": "m0"}]}
    assert aws["ddb"].Table(settings.table_idempotency).scan()["Items"] == []
    # El reintento de SQS procesa la lectura normalmente.
    Processor(settings, aws["repo"], thresholds, no_model, clock=lambda: now).handle(sqs([reading(0)]))
    assert len(aws["firehose"].records) == 1


def test_out_of_order_reading_does_not_overwrite_machine(processor, aws, reading, sqs, settings):
    processor.handle(sqs([reading(5)]))
    processor.handle(sqs([reading(1)]))
    machine = aws["ddb"].Table(settings.table_machines).get_item(Key={"pk": "OP-01#EX-023", "sk": "META"})["Item"]
    assert machine["last_seen_at"] == reading(5)["timestamp"]


def test_ml_failure_falls_back_to_rules_and_stats(aws, thresholds, reading, sqs, settings, now):
    class BrokenModel:
        def score(self, r):
            raise RuntimeError("S3 caído")

    result = Processor(settings, aws["repo"], thresholds, BrokenModel(), clock=lambda: now).handle(sqs([reading(0)]))
    assert result == {"batchItemFailures": []}
