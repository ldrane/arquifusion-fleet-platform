"""replicar: punto de entrada de la Lambda (RF-05, RF-15.3, MH-HA-03).

Handler delgado: el lote de DynamoDB Streams va a service.py. Si Firestore falla se relanza la excepción
para que el event source mapping reintente (bisect) y, agotados los reintentos, mande el lote a la DLQ.
"""

import service
from arquifusion_shared.observability import logger, tracer


@logger.inject_lambda_context(clear_state=True)
@tracer.capture_lambda_handler
def handler(event, context):
    stats = service.run(event)
    logger.info("replicado", extra=stats)
    return stats
