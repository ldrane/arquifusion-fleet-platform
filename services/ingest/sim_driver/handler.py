"""Handler de la Lambda `sim-driver` (TAREA-07): gemelo de flota serverless.

EventBridge Scheduler la invoca cada minuto. Si el estado en SSM está deshabilitado o expiró, no hace nada.
No loguea secretos: la URL de Telegram no aplica aquí y la API key nunca se imprime.
"""

import json
import os
import time
from datetime import UTC, datetime

import boto3
import service
from arquifusion_shared.observability import logger, tracer

from simulator.sender import TelemetrySender

STAGE = os.environ.get("STAGE", "dev")
STATE_PARAM = os.environ.get("SIM_STATE_PARAM") or f"/arquifusion/{STAGE}/sim/state"
URL_PARAM = f"/arquifusion/{STAGE}/api/url"
API_KEY_SECRET = f"arquifusion/{STAGE}/simulator/api-key"

_ssm = boto3.client("ssm")
_secrets = boto3.client("secretsmanager")


def _get_state() -> dict:
    resp = _ssm.get_parameter(Name=STATE_PARAM)
    return json.loads(resp["Parameter"]["Value"] or "{}")


def _put_state(state: dict) -> None:
    _ssm.put_parameter(Name=STATE_PARAM, Value=json.dumps(state), Type="String", Overwrite=True)


def _api_url() -> str:
    return _ssm.get_parameter(Name=URL_PARAM)["Parameter"]["Value"]


def _api_key() -> str:
    """El secreto puede ser texto plano o el JSON `{api_key, api_url, operation_id}` que crea infra/ingest."""
    raw = _secrets.get_secret_value(SecretId=API_KEY_SECRET)["SecretString"]
    try:
        return json.loads(raw)["api_key"]
    except (ValueError, KeyError, TypeError):
        return raw.strip()


@logger.inject_lambda_context(correlation_id_path="correlation_id")
@tracer.capture_lambda_handler
def handler(event, context):
    sender = TelemetrySender(_api_url(), _api_key())
    deps = {
        "get_state": _get_state,
        "put_state": _put_state,
        "send": sender.send,
        "now": lambda: datetime.now(UTC),
        "sleep": time.sleep,
        "remaining_ms": lambda: context.get_remaining_time_in_millis() if context is not None else 60_000,
    }
    result = service.run(deps)
    logger.info("sim-driver", extra={"result": result})
    return result
