"""ia_gemini: punto de entrada de la Lambda (RF-02.6, RF-12.3, RF-14, RF-16.8).

Handler delgado: arma las dependencias una vez por contenedor y delega en service.py.
"""

import json
import os

import boto3
import service
from arquifusion_shared.observability import logger, tracer
from aws_lambda_powertools.utilities import parameters
from ia_tools import ToolBox
from llm_client import build_clients

SECRET_MAX_AGE_S = 300


def _api_key() -> str:
    """Solo con LLM_PROVIDER=gemini.

    Lee la API key de Secrets Manager con caché de 5 min. Acepta texto plano o `{"api_key": "..."}`."""
    secret = parameters.get_secret(os.environ["GEMINI_SECRET_NAME"], max_age=SECRET_MAX_AGE_S)
    try:
        return json.loads(secret)["api_key"]
    except (ValueError, KeyError, TypeError):
        return secret.strip()


# Cadena de proveedores LLM por env (RF-02.6, RF-14): LLM_PROVIDER="gemini,bedrock", GEMINI_MODEL,
# BEDROCK_MODEL_ID, LLM_TIMEOUT_S. El primero que responde gana; si todos fallan, motor determinista.
_llm = build_clients(gemini_api_key_provider=_api_key)
_dynamodb = boto3.resource("dynamodb")


def _tools(zone_scope: str | None) -> ToolBox:
    return ToolBox(
        _dynamodb.Table(os.environ["TABLE_MACHINES"]),
        _dynamodb.Table(os.environ["TABLE_INCIDENTS"]),
        _dynamodb.Table(os.environ["TABLE_INSIGHTS"]),
        zone_scope,
    )


@logger.inject_lambda_context(correlation_id_path="correlation_id")
@tracer.capture_lambda_handler
def handler(event, context):
    if service.is_api_event(event):
        return service.handle_api(event, _llm, _tools)
    return service.handle_task(event, _llm)
