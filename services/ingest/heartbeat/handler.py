"""heartbeat: punto de entrada de la Lambda (OBS-09).

Handler delgado: arma las dependencias una vez por contenedor y delega en `service.Heartbeat`.
"""

import json
import os

import boto3
from arquifusion_shared.observability import logger, metrics, tracer
from aws_lambda_powertools.metrics import MetricUnit
from service import EVENT_SOURCE, EVENT_TYPE, Heartbeat, HeartbeatConfig

_events = boto3.client("events")
_bus = os.environ["EVENT_BUS_NAME"]


def _publish(detail: dict) -> None:
    response = _events.put_events(
        Entries=[
            {
                "Source": EVENT_SOURCE,
                "DetailType": EVENT_TYPE,
                "EventBusName": _bus,
                "Detail": json.dumps(detail),
            }
        ]
    )
    if response.get("FailedEntryCount"):
        raise RuntimeError(f"EventBridge rechazó MachineSilent: {response['Entries']}")
    logger.info(
        "MachineSilent emitido",
        extra={"machine_id": detail["data"]["machine_id"], "correlation_id": detail["correlation_id"]},
    )


_heartbeat = Heartbeat(
    boto3.resource("dynamodb").Table(os.environ["TABLE_MACHINES"]),
    _publish,
    HeartbeatConfig(
        default_interval_s=int(os.environ.get("DEFAULT_INTERVAL_S", "60")),
        silence_factor=int(os.environ.get("SILENCE_FACTOR", "3")),
    ),
)


@logger.inject_lambda_context
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event, context):
    result = _heartbeat.run()
    metrics.add_metric(name="MachinesSilenced", unit=MetricUnit.Count, value=result["silenced"])
    logger.info("Heartbeat completado", extra=result)
    return result
