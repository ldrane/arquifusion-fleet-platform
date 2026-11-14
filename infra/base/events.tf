# Bus de eventos de la plataforma (contratos.md §3)
resource "aws_cloudwatch_event_bus" "fleet" {
  name = "${local.prefix}-fleet-events"
}

# Un topic SNS por rol (notificar publica aquí según notification-rules, §10)
locals {
  roles = ["operador", "tecnico", "mantenimiento", "supervisor", "admin", "gerencia"]
}

resource "aws_sns_topic" "alerts" {
  for_each = toset(local.roles)
  name     = "${local.prefix}-alerts-${each.key}"
}

# Suscripciones email opcionales por rol (filtran por zona con el atributo `zone` que pone notificar)
resource "aws_sns_topic_subscription" "alerts_email" {
  for_each  = var.alert_emails
  topic_arn = aws_sns_topic.alerts[split("|", each.key)[0]].arn
  protocol  = "email"
  endpoint  = split("|", each.key)[1]
  filter_policy = each.value == "*" ? null : jsonencode({
    zone = [each.value]
  })
}

# Alarmas de plataforma (DLQ, errores, throttling, SFN fallida) — MH-OBS-03. Lo usan A, B y C por nombre.
resource "aws_sns_topic" "platform_alarms" {
  name = "${local.prefix}-platform-alarms"
}

resource "aws_sns_topic_subscription" "platform_alarms_email" {
  for_each  = toset(var.alarm_emails)
  topic_arn = aws_sns_topic.platform_alarms.arn
  protocol  = "email"
  endpoint  = each.value
}
