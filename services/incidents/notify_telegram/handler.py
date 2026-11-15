"""notify_telegram: punto de entrada de la Lambda (RF-10.1, RF-10.2).

Handler delgado: fija el correlation_id (#27), arma las dependencias reales (secreto, DynamoDB) y delega en
service.py.
"""
import os
import time

import service
from arquifusion_shared import correlation
from arquifusion_shared.observability import logger, tracer

DEDUP_TTL_S = 24 * 3600

_cache: dict = {}


def _config():  # pragma: no cover - requiere AWS
    from aws_lambda_powertools.utilities import parameters

    try:
        raw = parameters.get_secret(os.environ["TELEGRAM_SECRET_NAME"], max_age=300)
    except parameters.exceptions.GetParameterError:
        return None  # secreto sin versión: aún no se cargó el token
    return service.parse_config(raw)


def _tables():  # pragma: no cover - requiere AWS
    if "ddb" not in _cache:
        import boto3

        ddb = boto3.resource("dynamodb")
        _cache["ddb"] = (ddb.Table(os.environ["TABLE_IDEMPOTENCY"]), ddb.Table(os.environ["TABLE_INCIDENTS"]))
    return _cache["ddb"]


def _claim(key: str) -> bool:  # pragma: no cover - requiere AWS
    idem, _ = _tables()
    now = int(time.time())
    try:
        idem.put_item(
            Item={"pk": key, "expires_at": now + DEDUP_TTL_S, "created_at": now},
            ConditionExpression="attribute_not_exists(pk) OR expires_at < :now",
            ExpressionAttributeValues={":now": now},
        )
        return True
    except idem.meta.client.exceptions.ConditionalCheckFailedException:
        return False


def _release(key: str) -> None:  # pragma: no cover - requiere AWS
    _tables()[0].delete_item(Key={"pk": key})


def _incident(incident_id: str):  # pragma: no cover - requiere AWS
    return _tables()[1].get_item(Key={"pk": f"INC#{incident_id}", "sk": "META"}).get("Item")


DEPS = {"config": _config, "claim": _claim, "release": _release, "incident": _incident,
        "send": service.send_message}


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event, context):
    logger.set_correlation_id(correlation.from_any(event))
    types = [t.strip() for t in os.environ.get("TELEGRAM_EVENT_TYPES", "").split(",") if t.strip()]
    notifier = service.TelegramNotifier(DEPS, types or service.DEFAULT_EVENT_TYPES, os.environ.get("APP_URL", ""))
    result = notifier.run(event)
    logger.info("telegram", extra=result)
    return result
