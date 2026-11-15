# Alarma de concurrencia total de Lambda en la cuenta (AWS Academy: <=10 en paralelo; RNF de costo/operación).
# Las Lambdas tienen concurrencia reservada (infra/{ingest,incidents,query}: var.reserved_concurrency) y las SFN
# reintentan Lambda.TooManyRequestsException; esta alarma avisa si el pico se acerca al límite.
resource "aws_cloudwatch_metric_alarm" "lambda_concurrency" {
  alarm_name          = "${local.prefix}-lambda-concurrency-high"
  alarm_description   = "ConcurrentExecutions de Lambda >= 8 (límite AWS Academy: 10). Revisar simulador/tormenta de incidentes."
  namespace           = "AWS/Lambda"
  metric_name         = "ConcurrentExecutions"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 8
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.platform_alarms.arn]
}
