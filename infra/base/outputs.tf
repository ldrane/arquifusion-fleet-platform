output "table_names" {
  description = "Nombres físicos de las tablas DynamoDB"
  value = {
    machines           = aws_dynamodb_table.machines.name
    technicians        = aws_dynamodb_table.technicians.name
    catalog            = aws_dynamodb_table.catalog.name
    inventory          = aws_dynamodb_table.inventory.name
    notification_rules = aws_dynamodb_table.notification_rules.name
    incidents          = aws_dynamodb_table.incidents.name
    machine_state      = aws_dynamodb_table.machine_state.name
    anomalies          = aws_dynamodb_table.anomalies.name
    idempotency        = aws_dynamodb_table.idempotency.name
    audit_events       = aws_dynamodb_table.audit_events.name
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
