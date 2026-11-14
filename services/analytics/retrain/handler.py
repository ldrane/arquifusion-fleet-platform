"""retrain: pasos de la SFN Reentrenamiento (RF-13.2). Handlers delgados; la lógica está en service.py.

La misma imagen sirve dos Lambdas: `handler.handler` (entrenar) y `handler.promote` (promover).
"""

import os
from datetime import UTC, datetime

import boto3
import service
from arquifusion_shared.observability import logger, tracer

_s3 = boto3.client("s3")
_ssm = boto3.client("ssm")
_dynamodb = boto3.resource("dynamodb")


@logger.inject_lambda_context(correlation_id_path="correlation_id")
@tracer.capture_lambda_handler
def handler(event, context):
    return service.train_step(event, _s3, os.environ["ARTIFACTS_BUCKET"], os.environ["LAKE_BUCKET"], datetime.now(UTC))


@logger.inject_lambda_context(correlation_id_path="correlation_id")
@tracer.capture_lambda_handler
def promote(event, context):
    return service.promote_step(
        event,
        _s3,
        _ssm,
        _dynamodb.Table(os.environ["TABLE_INSIGHTS"]),
        os.environ["ARTIFACTS_BUCKET"],
        os.environ["STAGE"],
        datetime.now(UTC),
    )
