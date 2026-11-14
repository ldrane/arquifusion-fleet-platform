"""kpis_report: cierre de AnalisisDiario (RF-10.3, RF-11.4). Handler delgado; la lógica está en service.py."""

import os

import boto3
import service
from analytics_common.run_context import parse_event
from arquifusion_shared.observability import logger, tracer

_athena = boto3.client("athena")
_dynamodb = boto3.resource("dynamodb")
_invoke_ia = service.lambda_invoker(boto3.client("lambda"), os.environ["IA_GEMINI_FUNCTION"])


@logger.inject_lambda_context(correlation_id_path="correlation_id")
@tracer.capture_lambda_handler
def handler(event, context):
    return service.run(
        parse_event(event),
        athena=_athena,
        machines_table=_dynamodb.Table(os.environ["TABLE_MACHINES"]),
        incidents_table=_dynamodb.Table(os.environ["TABLE_INCIDENTS"]),
        insights_table=_dynamodb.Table(os.environ["TABLE_INSIGHTS"]),
        invoke_ia=_invoke_ia,
        branches=event.get("branches"),
        catalog_table=_dynamodb.Table(os.environ["TABLE_CATALOG"]),
    )
