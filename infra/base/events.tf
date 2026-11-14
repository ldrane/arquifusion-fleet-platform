# Bus de eventos de la plataforma
resource "aws_cloudwatch_event_bus" "fleet" {
  name = "${local.prefix}-fleet-events"
}

# Un topic SNS por rol (notificar publica aquí según notification-rules)
locals {
  roles = ["operador", "tecnico", "mantenimiento", "supervisor", "admin", "gerencia"]
}

resource "aws_sns_topic" "alerts" {
  for_each = toset(local.roles)
  name     = "${local.prefix}-alerts-${each.key}"
}
