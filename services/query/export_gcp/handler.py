"""export_gcp: punto de entrada de la Lambda (TAREA-13). Handler delgado; la lógica está en service.py.

La invoca AnalisisDiario (estado `ExportarGCP`, best-effort) desde el stack query, que ya trae la layer de C con
`google-auth`. Fuera de VPC: sale a BigQuery por Internet (la VPC no tiene NAT).
"""

import os

import boto3
import service
from arquifusion_shared import correlation
from arquifusion_shared.observability import logger, tracer
from query_common import gcp

_dynamodb = boto3.resource("dynamodb")
_secrets = boto3.client("secretsmanager")
_athena = boto3.client("athena")
_s3 = boto3.client("s3")


@logger.inject_lambda_context(clear_state=True)
@tracer.capture_lambda_handler
def handler(event, context):
    logger.set_correlation_id(correlation.from_any(event))  # TRZ-01
    sa_info = gcp.load_service_account(os.environ.get("GCP_SA_SECRET_NAME", ""), _secrets)
    project = os.environ.get("BQ_PROJECT") or sa_info["project_id"]
    bigquery = service.BigQuery(project, os.environ["BQ_DATASET"], service.authorized_transport(sa_info))
    result = service.run(
        event,
        athena=_athena,
        s3=_s3,
        incidents_table=_dynamodb.Table(os.environ["TABLE_INCIDENTS"]),
        insights_table=_dynamodb.Table(os.environ["TABLE_INSIGHTS"]),
        bigquery=bigquery,
    )
    logger.info("export_gcp", extra=result)
    return result
