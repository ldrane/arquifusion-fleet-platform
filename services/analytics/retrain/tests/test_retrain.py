import io
import json
from datetime import UTC, datetime, timedelta

import boto3
import joblib
import numpy as np
import pandas as pd
import pytest
import retrain_model
import service
from analytics_testkit import create_table
from arquifusion_ml.features import FEATURES, to_vector
from arquifusion_ml.model_store import ModelMetadata, metadata_key, model_key
from moto import mock_aws

START = datetime(2026, 8, 1, tzinfo=UTC)
NOW = datetime(2026, 11, 14, tzinfo=UTC)


def synthetic_lake(days=40, machines=4, step_min=30, seed=1):
    """Lecturas normales + una falla por degradación (48 h) por máquina en la segunda mitad del periodo."""
    rng = np.random.default_rng(seed)
    rows, failures = [], []
    steps = days * 24 * 60 // step_min
    for m in range(machines):
        mid = f"EX-{m:03d}"
        failure_at = START + timedelta(days=days * 0.55 + m * days * 0.1)
        precursor = failure_at - timedelta(hours=48)
        repair_end = failure_at + timedelta(hours=12)
        failures.append(
            {
                "machine_id": mid,
                "machine_type": "excavator",
                "zone": "norte",
                "kind": "degradacion",
                "precursor_start": precursor,
                "failure_at": failure_at,
                "repair_end": repair_end,
            }
        )
        for i in range(steps):
            ts = START + timedelta(minutes=step_min * i)
            ramp = (ts - precursor) / (failure_at - precursor) if precursor <= ts < failure_at else 0.0
            in_repair = failure_at <= ts < repair_end
            rows.append(
                {
                    "machine_id": mid,
                    "ts": ts.isoformat(),
                    "sim_scenario": "degradacion" if ramp else None,
                    "temperature_c": rng.normal(85, 2) + 25 * ramp,
                    "vibration_mm_s": rng.normal(4, 0.3) + 6 * ramp,
                    "pressure_bar": rng.normal(200, 5),
                    "fuel_rate_lph": rng.normal(32, 1) + 8 * ramp,
                    "load_pct": rng.normal(70, 5),
                    "rpm": rng.normal(1700, 40),
                    "speed_kmh": rng.normal(6, 1),
                    "state": "stopped" if in_repair else "operating",
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(failures)


@pytest.fixture(scope="module")
def trained():
    frame, failures = synthetic_lake()
    return retrain_model.train(frame, failures, "v1", NOW)


def test_model_detects_failures_with_lead_time(trained):
    md = trained.metadata
    assert md.features == list(FEATURES) and md.promoted is False
    assert md.recall >= 0.5 and md.precision >= 0.5
    assert md.mean_lead_time_hours > 0 and md.extra["failure_detection_rate"] > 0
    assert md.extra["label_source"] == "labels/failures.parquet"


def test_score_scale_matches_procesar(trained):
    """procesar compara -score_samples(to_vector(reading)) con score_threshold en la misma escala 0-1."""
    normal = {
        "temperature_c": 85,
        "vibration_mm_s": 4,
        "pressure_bar": 200,
        "fuel_rate_lph": 32,
        "load_pct": 70,
        "rpm": 1700,
        "speed_kmh": 6,
    }
    failing = {**normal, "temperature_c": 110, "vibration_mm_s": 10, "fuel_rate_lph": 40}
    score = lambda r: float(-trained.model.score_samples([to_vector(r)])[0])  # noqa: E731
    assert 0 < score(normal) < trained.metadata.score_threshold < score(failing) < 1


def test_labels_ignore_productivity_scenarios():
    frame = retrain_model.prepare(
        pd.DataFrame(
            [
                {
                    "machine_id": "EX-1",
                    "ts": "2026-11-01T00:00:00Z",
                    "sim_scenario": s,
                    "temperature_c": 1,
                    "vibration_mm_s": 1,
                    "pressure_bar": 1,
                    "fuel_rate_lph": 1,
                    "load_pct": 1,
                    "rpm": 1,
                    "speed_kmh": 1,
                }
                for s in ("ociosa", "sobreexplotada", "combustible", None)
            ]
        )
    )
    positive, excluded = retrain_model.label(frame, None)
    assert positive.tolist() == [False, False, True, False] and not excluded.any()


def test_promotion_rule_and_versions():
    base = ModelMetadata("v1", "t", list(FEATURES), 0.6, 0.8, 0.8, 10.0, True, extra={"f1": 0.8})
    worse = ModelMetadata("v2", "t", list(FEATURES), 0.6, 0.5, 0.5, 10.0, False, extra={"f1": 0.5})
    assert retrain_model.is_better(worse, None) and not retrain_model.is_better(worse, base)
    assert retrain_model.next_version("v3") == "v4" and retrain_model.next_version("v0") == "v1"
    assert retrain_model.next_version(None) == "v1"


def test_train_and_promote_steps_on_s3():
    frame, failures = synthetic_lake(days=30, machines=3)
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        ssm = boto3.client("ssm", region_name="us-east-1")
        for bucket in ("artifacts", "lake"):
            s3.create_bucket(Bucket=bucket)
        s3.put_object(Bucket="artifacts", Key="athena-results/q1.csv", Body=frame.to_csv(index=False).encode())
        buf = io.BytesIO()
        failures.to_parquet(buf, index=False)
        s3.put_object(Bucket="lake", Key=service.FAILURES_KEY, Body=buf.getvalue())
        insights = create_table("insights")

        out = service.train_step(
            {
                "output_location": "s3://artifacts/athena-results/q1.csv",
                "active_version": "v0",
                "correlation_id": "cid",
            },
            s3,
            "artifacts",
            "lake",
            NOW,
        )
        assert out["candidate_version"] == "v1" and out["better"] is True and out["current"] is None
        model = joblib.load(io.BytesIO(s3.get_object(Bucket="artifacts", Key=model_key("v1"))["Body"].read()))
        assert hasattr(model, "score_samples")

        service.promote_step(
            {"candidate_version": "v1", "correlation_id": "cid"}, s3, ssm, insights, "artifacts", "dev", NOW
        )
        assert ssm.get_parameter(Name="/arquifusion/dev/model/active_version")["Parameter"]["Value"] == "v1"
        meta = json.loads(s3.get_object(Bucket="artifacts", Key=metadata_key("v1"))["Body"].read())
        assert meta["promoted"] is True
        api = insights.get_item(Key={"pk": "ml_model", "sk": "LATEST"})["Item"]["data"]
        assert set(api) == {"model_version", "trained_at", "precision", "recall", "mean_lead_time_hours", "promoted"}

        again = service.train_step(
            {
                "output_location": "s3://artifacts/athena-results/q1.csv",
                "active_version": "v1",
                "correlation_id": "cid",
            },
            s3,
            "artifacts",
            "lake",
            NOW,
        )
        assert again["candidate_version"] == "v2" and again["current"]["model_version"] == "v1"
        assert again["better"] is True  # mismos datos y semilla: F1 igual → se promueve (≥)


def test_too_little_data_fails_loudly():
    with pytest.raises(ValueError):
        retrain_model.train(pd.DataFrame(synthetic_lake(days=1, machines=1)[0].head(10)), None, "v1", NOW)
