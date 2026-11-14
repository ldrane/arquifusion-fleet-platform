"""procesar: punto de entrada de la Lambda (RF-02, RF-09, RNF-07).

Handler delgado: arma las dependencias una vez por contenedor y delega en `service.Processor`.
"""

import boto3
from arquifusion_ml.model_store import active_version_param
from arquifusion_shared.observability import logger, metrics, tracer
from botocore.exceptions import ClientError
from ingest_procesar.config import Settings
from ingest_procesar.model import ModelProvider
from ingest_procesar.repository import Repository
from ingest_procesar.rules import ThresholdProvider
from service import Processor

_settings = Settings.from_env()
_ssm = boto3.client("ssm")
_s3 = boto3.client("s3")


def _ssm_value(name: str) -> str | None:
    try:
        return _ssm.get_parameter(Name=name)["Parameter"]["Value"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ParameterNotFound":
            return None
        raise


def _read_model_object(key: str) -> bytes:
    return _s3.get_object(Bucket=_settings.model_bucket, Key=key)["Body"].read()


_processor = Processor(
    settings=_settings,
    repo=Repository(_settings, boto3.resource("dynamodb"), boto3.client("firehose"), boto3.client("events")),
    thresholds=ThresholdProvider(
        lambda machine_type: _ssm_value(f"/arquifusion/{_settings.stage}/thresholds/{machine_type}"),
        ttl_s=_settings.cache_ttl_s,
    ),
    models=ModelProvider(
        lambda: _ssm_value(active_version_param(_settings.stage)),
        _read_model_object,
        ttl_s=_settings.cache_ttl_s,
    ),
)


@logger.inject_lambda_context
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event, context):
    return _processor.handle(event)
