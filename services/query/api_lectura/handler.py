"""api_lectura: punto de entrada de la Lambda (RF-05, RF-11, RF-02.3, RF-16).

Handler delgado: correlation_id, logging y envoltorio estándar. La lógica va en service.py,
que devuelve `(data, meta)` (meta lleva `next_cursor` en las listas paginadas).
"""

import service
from arquifusion_shared import correlation, response
from arquifusion_shared.errors import ApiError
from arquifusion_shared.observability import logger, tracer


@logger.inject_lambda_context(clear_state=True)
@tracer.capture_lambda_handler
def handler(event, context):
    cid = correlation.from_api_event(event)
    logger.set_correlation_id(cid)
    logger.append_keys(route=f"{event.get('httpMethod')} {event.get('resource')}")
    try:
        data, meta = service.run(event)
        return response.ok(data, cid, meta)
    except ApiError as err:
        logger.warning("api_error", extra={"code": err.code, "status": err.status, "error_message": err.message})
        return response.error(err, cid)
    except Exception:
        logger.exception("unhandled")
        return response.error(ApiError("Error interno"), cid)
