# Publicado también en SSM /arquifusion/<stage>/... (main.tf, aws_ssm_parameter.out)

output "gestion_incidente_arn" {
  value = aws_sfn_state_machine.gestion_incidente.arn
}

output "lambda_arns" {
  value = { for k, f in aws_lambda_function.fn : k => f.arn }
}

output "events_dlq_url" {
  value = aws_sqs_queue.events_dlq.url
}
