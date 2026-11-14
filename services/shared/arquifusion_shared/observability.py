"""Logger, tracer y métricas de Powertools con nombres de servicio uniformes."""
from aws_lambda_powertools import Logger, Metrics, Tracer

logger = Logger()          # POWERTOOLS_SERVICE_NAME por variable de entorno
tracer = Tracer()
metrics = Metrics(namespace="ArquiFusion")  # nunca machine_id como dimensión
