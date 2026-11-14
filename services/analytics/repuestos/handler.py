"""repuestos: rama de AnalisisDiario (RF-04). Handler delgado; la lógica está en service.py."""

import os

import boto3
import service
from analytics_common.run_context import parse_event
from arquifusion_shared.observability import logger, tracer

_athena = boto3.client("athena")
_dynamodb = boto3.resource("dynamodb")


@logger.inject_lambda_context(correlation_id_path="correlation_id")
@tracer.capture_lambda_handler
def handler(event, context):
    return service.run(
        parse_event(event),
        athena=_athena,
        machines_table=_dynamodb.Table(os.environ["TABLE_MACHINES"]),
        records_table=_dynamodb.Table(os.environ["TABLE_MAINTENANCE_RECORDS"]),
        inventory_table=_dynamodb.Table(os.environ["TABLE_INVENTORY"]),
        catalog_table=_dynamodb.Table(os.environ["TABLE_CATALOG"]),
        insights_table=_dynamodb.Table(os.environ["TABLE_INSIGHTS"]),
    )
