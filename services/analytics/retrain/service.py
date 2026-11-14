"""Pasos del workflow `Reentrenamiento` (RF-13.2, MH-SFN-03, MH-AI-04).

- `train_step`: lee el resultado de Athena (CSV en S3) y `labels/failures.parquet` del lake, entrena el candidato
  y lo guarda en `s3://<artifacts>/models/isolation_forest/<vN>/` con `promoted=false`.
- `promote_step`: marca el candidato como promovido, actualiza SSM `/arquifusion/{stage}/model/active_version`
  (procesar lo recoge en ≤ 5 min) y publica `insights` `ml_model` (GET /v1/ml/model).
"""

import io
import json
from datetime import datetime
from urllib.parse import urlparse

import joblib
import pandas as pd
import retrain_model
from analytics_common.insights_store import write_insight
from arquifusion_ml.model_store import ModelMetadata, active_version_param, metadata_key, model_key
from arquifusion_shared.observability import logger
from botocore.exceptions import ClientError

FAILURES_KEY = "labels/failures.parquet"
NO_MODEL = "v0"


def _get(s3, bucket: str, key: str) -> bytes | None:
    try:
        return s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise


def read_training_frame(s3, output_location: str) -> pd.DataFrame:
    url = urlparse(output_location)
    body = _get(s3, url.netloc, url.path.lstrip("/"))
    if body is None:
        raise ValueError(f"No existe el resultado de Athena {output_location}")
    return pd.read_csv(io.BytesIO(body))


def read_failures(s3, lake_bucket: str) -> pd.DataFrame | None:
    body = _get(s3, lake_bucket, FAILURES_KEY)
    if body is None:
        logger.warning("Sin labels/failures.parquet: se etiqueta con sim_scenario")
        return None
    return pd.read_parquet(io.BytesIO(body))


def load_metadata(s3, bucket: str, version: str | None) -> ModelMetadata | None:
    if not version or version == NO_MODEL:
        return None
    body = _get(s3, bucket, metadata_key(version))
    return ModelMetadata.from_dict(json.loads(body)) if body else None


def save_candidate(s3, bucket: str, result: retrain_model.TrainResult) -> None:
    version = result.metadata.model_version
    buffer = io.BytesIO()
    joblib.dump(result.model, buffer)
    s3.put_object(Bucket=bucket, Key=model_key(version), Body=buffer.getvalue())
    s3.put_object(
        Bucket=bucket,
        Key=metadata_key(version),
        Body=json.dumps(result.metadata.to_dict()).encode(),
        ContentType="application/json",
    )


def train_step(event: dict, s3, artifacts_bucket: str, lake_bucket: str, now: datetime) -> dict:
    """Evento: `{"output_location", "active_version", "correlation_id"}` (desde la SFN)."""
    active = event.get("active_version") or NO_MODEL
    frame = read_training_frame(s3, event["output_location"])
    result = retrain_model.train(frame, read_failures(s3, lake_bucket), retrain_model.next_version(active), now)
    save_candidate(s3, artifacts_bucket, result)
    current = load_metadata(s3, artifacts_bucket, active)
    better = retrain_model.is_better(result.metadata, current)
    logger.info("Modelo candidato entrenado", extra={"candidate": result.metadata.to_dict(), "better": better})
    return {
        "candidate_version": result.metadata.model_version,
        "active_version": active,
        "better": better,
        "candidate": {**result.metadata.api_view(), **result.metadata.extra},
        "current": ({**current.api_view(), **current.extra} if current else None),
    }


def promote_step(event: dict, s3, ssm, insights_table, artifacts_bucket: str, stage: str, now: datetime) -> dict:
    """Evento: `{"candidate_version", "correlation_id"}`."""
    version = event["candidate_version"]
    metadata = load_metadata(s3, artifacts_bucket, version)
    if metadata is None:
        raise ValueError(f"No existe la metadata del modelo {version}")
    metadata.promoted = True
    s3.put_object(
        Bucket=artifacts_bucket,
        Key=metadata_key(version),
        Body=json.dumps(metadata.to_dict()).encode(),
        ContentType="application/json",
    )
    ssm.put_parameter(Name=active_version_param(stage), Value=version, Type="String", Overwrite=True)
    run_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    write_insight(
        insights_table, "ml_model", metadata.api_view(), run_at, event.get("correlation_id") or "reentrenamiento"
    )
    return {"promoted_version": version}
