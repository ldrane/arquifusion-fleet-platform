# Salidas de base. Los demás stacks referencian por NOMBRE (contratos.md §9) o por SSM /arquifusion/<stage>/...

output "table_names" {
  description = "Nombres físicos de las tablas DynamoDB (variables TABLE_<NOMBRE>, contratos.md §1.1)"
  value = {
    machines            = aws_dynamodb_table.machines.name
    machine_state       = aws_dynamodb_table.machine_state.name
    idempotency         = aws_dynamodb_table.idempotency.name
    anomalies           = aws_dynamodb_table.anomalies.name
    incidents           = aws_dynamodb_table.incidents.name
    technicians         = aws_dynamodb_table.technicians.name
    inventory           = aws_dynamodb_table.inventory.name
    catalog             = aws_dynamodb_table.catalog.name
    warehouses          = aws_dynamodb_table.warehouses.name
    notification_rules  = aws_dynamodb_table.notification_rules.name
    audit_events        = aws_dynamodb_table.audit_events.name
    maintenance_records = aws_dynamodb_table.maintenance_records.name
    insights            = aws_dynamodb_table.insights.name
  }
}

output "event_bus_name" {
  value = aws_cloudwatch_event_bus.fleet.name
}

output "event_bus_arn" {
  value = aws_cloudwatch_event_bus.fleet.arn
}

output "sns_topic_arns" {
  value = { for role, t in aws_sns_topic.alerts : role => t.arn }
}

output "platform_alarms_topic_arn" {
  value = aws_sns_topic.platform_alarms.arn
}

output "api_id" {
  value = aws_api_gateway_rest_api.api.id
}

output "api_url" {
  description = "VITE_API_URL del front (incluye el stage v1; las rutas no llevan /v1)"
  value       = aws_api_gateway_stage.v1.invoke_url
}

output "api_execution_arn" {
  value = aws_api_gateway_rest_api.api.execution_arn
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.users.id
}

output "cognito_client_id" {
  description = "VITE_COGNITO_CLIENT_ID"
  value       = aws_cognito_user_pool_client.web.id
}

output "bridge_secret_name" {
  value = aws_secretsmanager_secret.bridge_gcp.name
}

output "gcp_service_account_secret_name" {
  value = aws_secretsmanager_secret.gcp_service_account.name
}

# ---------------------------------------------------------------- SSM (para no depender del state de base)
locals {
  ssm = {
    "api/id"                     = aws_api_gateway_rest_api.api.id
    "api/root_resource_id"       = aws_api_gateway_rest_api.api.root_resource_id
    "api/execution_arn"          = aws_api_gateway_rest_api.api.execution_arn
    "api/url"                    = aws_api_gateway_stage.v1.invoke_url
    "api/authorizer_id"          = aws_api_gateway_authorizer.cognito.id
    "cognito/user_pool_id"       = aws_cognito_user_pool.users.id
    "cognito/user_pool_arn"      = aws_cognito_user_pool.users.arn
    "cognito/client_id"          = aws_cognito_user_pool_client.web.id
    "sns/platform_alarms_arn"    = aws_sns_topic.platform_alarms.arn
    "sns/alerts_topic_arn_prefix" = "arn:aws:sns:${var.aws_region}:${local.account_id}:${local.prefix}-alerts-"
    "events/bus_arn"             = aws_cloudwatch_event_bus.fleet.arn
  }
}

resource "aws_ssm_parameter" "base" {
  for_each = local.ssm
  name     = "/arquifusion/${var.stage}/${each.key}"
  type     = "String"
  value    = each.value
}
