"""api_comandos: punto de entrada de la Lambda (RF-06.1, RF-06.4, RF-11.1, RF-13.2, RF-16.5).

Handler delgado: fija el correlation_id desde `X-Correlation-Id` (#27) y delega en service.py.
"""
from arquifusion_shared import correlation
from arquifusion_shared.observability import logger, tracer

import service


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event, context):
    cid = correlation.from_api_event(event)
    headers = event.get("headers") or {}
    if not any(k.lower() == "x-correlation-id" for k in headers):
        event["headers"] = {**headers, "X-Correlation-Id": cid}  # mismo id en logs y respuesta
    logger.set_correlation_id(cid)
    return service.run(event)
