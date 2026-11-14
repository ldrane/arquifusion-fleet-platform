"""incidente: punto de entrada de la Lambda (RF-06, RF-11.1, RF-11.2, TRZ-03).

Handler delgado: fija el correlation_id (#27) y delega en service.py. La lógica de negocio va en service.py.
"""
from arquifusion_shared import correlation
from arquifusion_shared.observability import logger, tracer

import service


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event, context):
    logger.set_correlation_id(correlation.from_any(event))
    logger.append_keys(incident_id=event.get("incident_id"), action=event.get("action"))
    return service.run(event)
