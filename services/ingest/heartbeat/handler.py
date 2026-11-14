"""heartbeat: punto de entrada de la Lambda (OBS-09).

Handler delgado: parsea, valida y delega en service.py. La lógica de negocio va en service.py.
"""
from arquifusion_shared.observability import logger, tracer

import service


@logger.inject_lambda_context(correlation_id_path="correlation_id")
@tracer.capture_lambda_handler
def handler(event, context):
    return service.run(event)
