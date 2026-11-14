"""correlacion: punto de entrada de la Lambda (RF-12).

Handler delgado: fija el correlation_id (#27) y delega en service.py. La lógica de negocio va en service.py.
"""
import service
from arquifusion_shared import correlation
from arquifusion_shared.observability import logger, tracer


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event, context):
    logger.set_correlation_id(correlation.from_any(event))
    return service.run(event)
