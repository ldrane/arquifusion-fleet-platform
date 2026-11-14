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
    hs = agg["vars"]["health_score"]
    assert hs["min"] <= hs["avg"] <= hs["max"] <= 100
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
    assert len(anomalies) == 3
    for item in anomalies:
        assert item["zone"] == "norte" and item["sk"].startswith(item["detected_at"] + "#")
        assert item["detected_at"].startswith("2026-11-13T") and item["anomaly_id"]
        assert "gsi1pk" not in item and "gsi1sk" not in item
    assert data["reading_ts"] in {a["detected_at"] for a in anomalies}


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


def test_seed_fields_are_never_overwritten(processor, aws, reading, sqs, settings):
    """#1: una lectura con modelo/zona/tipo distintos no cambia los campos maestros del seed."""
    table = aws["ddb"].Table(settings.table_machines)
    before = table.get_item(Key={"pk": "OP-01#EX-023", "sk": "META"})["Item"]
    rogue = reading(0, model="AF-EX350", type="loader", location={"lat": -14.4, "lon": -71.95, "zone": "este"})
    processor.handle(sqs([rogue]))

    after = table.get_item(Key={"pk": "OP-01#EX-023", "sk": "META"})["Item"]
    for field in ("model", "type", "zone", "home_location", "expected_interval_s", "operation_id", "seed_version"):
        assert after[field] == before[field], field
    assert after["last_seen_at"] == rogue["timestamp"] and after["location"]["zone"] == "norte"
    assert aws["firehose"].records[0]["zone"] == "norte"


def test_unknown_machine_is_discarded_without_ghost(processor, aws, reading, sqs, settings):
    ghost = reading(0, machine_id="ZZ-999")
    result = processor.handle(sqs([ghost, reading(1)]))

    assert result == {"batchItemFailures": []}
    table = aws["ddb"].Table(settings.table_machines)
    assert "Item" not in table.get_item(Key={"pk": "OP-01#ZZ-999", "sk": "META"})
    assert [r["machine_id"] for r in aws["firehose"].records] == ["EX-023"]


def test_update_machine_requires_existing_item(aws, settings):
    assert (
        aws["repo"].update_machine("OP-01#ZZ-999", {"status": "operational", "last_seen_at": "2026-11-13T00:00:00Z"})
        is False
    )
    assert "Item" not in aws["ddb"].Table(settings.table_machines).get_item(Key={"pk": "OP-01#ZZ-999", "sk": "META"})


def test_f18_reclamo_pending_vencido_se_reprocesa_y_done_es_duplicado(aws, settings, now):
    repo, table = aws["repo"], aws["ddb"].Table(settings.table_idempotency)
    t0 = int(now.timestamp())
    assert repo.claim_reading("EX-023", "ts", t0) is True
    assert table.get_item(Key={"pk": "EX-023#ts"})["Item"]["state"] == "pending"
    # reclamo pendiente vigente: duplicado
    assert repo.claim_reading("EX-023", "ts", t0 + 10) is False
    # la Lambda murió: pasado el TTL corto el reintento puede reclamar de nuevo
    assert repo.claim_reading("EX-023", "ts", t0 + settings.claim_pending_s + 1) is True
    repo.mark_done("EX-023", "ts", t0 + 100)
    item = table.get_item(Key={"pk": "EX-023#ts"})["Item"]
    assert item["state"] == "done" and int(item["expires_at"]) == t0 + 100 + settings.idempotency_ttl_s
    # ya `done`: duplicado aunque pase el TTL corto
    assert repo.claim_reading("EX-023", "ts", t0 + 10_000) is False


def test_f18_lectura_reclamada_por_lambda_muerta_no_se_pierde(processor, aws, reading, sqs, settings, now):
    r = reading(0)
    aws["repo"].claim_reading(r["machine_id"], r["timestamp"], int(now.timestamp()) - 3600)  # pending vencido
    processor.handle(sqs([r]))
    assert len(aws["firehose"].records) == 1
    item = aws["ddb"].Table(settings.table_idempotency).get_item(Key={"pk": f"{r['machine_id']}#{r['timestamp']}"})
    assert item["Item"]["state"] == "done"


def test_f19_timestamp_o_machine_id_no_string_se_descartan_sin_romper_el_lote(processor, aws, reading, sqs):
    bad = [reading(1, timestamp=12345), reading(2, machine_id=None), reading(3, machine_id=7), reading(4, location="x")]
    result = processor.handle(sqs([reading(0), *bad, reading(5)]))
    assert result == {"batchItemFailures": []}
    assert len(aws["firehose"].records) == 2
