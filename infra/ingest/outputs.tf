# Lo que otros stacks y el simulador necesitan de infra/ingest (contratos.md §9, #27).
# Los ARN que consumen B y C se publican además en SSM (/arquifusion/<stage>/...).

output "telemetry_api_url" {
  description = "Base del stage v1 para SIMULATOR_API_URL (el simulador agrega /telemetry)"
  value       = "https://${data.aws_api_gateway_rest_api.api.id}.execute-api.${data.aws_region.current.name}.amazonaws.com/${local.api_stage_name}"
}

output "telemetry_endpoint" {
  description = "URL completa de POST /telemetry"
  value       = local.telemetry_url
}

output "simulator_api_key_id" {
  description = "ID de la API key del simulador (valor: aws apigateway get-api-key --include-value o el secreto)"
  value       = aws_api_gateway_api_key.simulator.id
}

output "simulator_api_key_secret_name" {
  description = "Secreto con {api_key, api_url, operation_id} para el simulador"
  value       = aws_secretsmanager_secret.simulator_api_key.name
}

output "gemini_api_key_secret_name" {
  description = "Secreto donde cargar la API key de Google AI Studio (contratos.md §8.1)"
  value       = aws_secretsmanager_secret.gemini_api_key.name
}

output "ingest_queue_url" {
  value = aws_sqs_queue.ingest.url
}

output "ingest_dlq_url" {
  value = aws_sqs_queue.ingest_dlq.url
}

output "ia_gemini_function_arn" {
  value = aws_lambda_function.ia_gemini.arn
}

output "analisis_diario_arn" {
  value = aws_sfn_state_machine.analisis_diario.arn
}

output "reentrenamiento_arn" {
  value = aws_sfn_state_machine.reentrenamiento.arn
}

output "artifacts_bucket" {
  value = module.artifacts_bucket.id
}

output "lake_bucket" {
  value = module.lake_bucket.id
}

output "ecr_repository_url" {
  value = aws_ecr_repository.ml.repository_url
}
