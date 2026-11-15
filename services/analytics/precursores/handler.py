"""precursores: rama de AnalisisDiario (TAREA-12). Handler delgado; la lógica está en service.py."""

import os

import boto3
import service
from analytics_common.run_context import parse_event
from arquifusion_shared.observability import logger, tracer

_dynamodb = boto3.resource("dynamodb")


@logger.inject_lambda_context(correlation_id_path="correlation_id")
@tracer.capture_lambda_handler
def handler(event, context):
    return service.run(
        parse_event(event),
        incidents_table=_dynamodb.Table(os.environ["TABLE_INCIDENTS"]),
        anomalies_table=_dynamodb.Table(os.environ["TABLE_ANOMALIES"]),
        machines_table=_dynamodb.Table(os.environ["TABLE_MACHINES"]),
        insights_table=_dynamodb.Table(os.environ["TABLE_INSIGHTS"]),
    )
