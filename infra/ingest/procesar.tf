# Lambda procesar (imagen ECR): reglas + z-score + IsolationForest sobre cada lote de SQS.
# Cubre: RF-02, RF-09, RNF-07, MH-AI-01. Dueño: Persona A (worker 2).
# Imagen: docker build -f services/ingest/procesar/Dockerfile -t <repo>:procesar-<tag> .  (desde la raíz)

locals {
  procesar_name = "${local.prefix}-procesar"
  # Umbrales de la capa 1 POR MODELO, derivados del nominal del seed (μ+3σ / μ+4σ, #2). Se regeneran con
  # `python services/ingest/procesar/ingest_procesar/rules.py` y se ajustan luego en SSM sin redeploy.
  thresholds_by_model = jsondecode(file("${path.module}/../../services/ingest/procesar/thresholds_default.json")).models
}

resource "aws_cloudwatch_log_group" "procesar" {
  name              = "/aws/lambda/${local.procesar_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "procesar" {
  function_name = local.procesar_name
  description   = "Detección de anomalías en telemetría (RF-02, RF-09)"
  role          = local.lab_role
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.ml.repository_url}:procesar-${var.image_tag}"
  architectures = ["x86_64"]
  memory_size   = 1024
  timeout       = 55 # < visibilidad de la cola (60 s)

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = merge(local.common_env, {
      POWERTOOLS_SERVICE_NAME = "procesar"
      TABLE_MACHINES          = local.tables.machines
      TABLE_MACHINE_STATE     = local.tables.machine_state
      TABLE_IDEMPOTENCY       = local.tables.idempotency
      TABLE_ANOMALIES         = local.tables.anomalies
      FIREHOSE_STREAM         = aws_kinesis_firehose_delivery_stream.telemetry.name
      MODEL_BUCKET            = aws_s3_bucket.artifacts.bucket
    })
  }

  depends_on = [aws_cloudwatch_log_group.procesar]
}

resource "aws_lambda_event_source_mapping" "procesar_sqs" {
  event_source_arn                   = aws_sqs_queue.ingest.arn
  function_name                      = aws_lambda_function.procesar.arn
  batch_size                         = 100
  maximum_batching_window_in_seconds = 5
  function_response_types            = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = 10 # acota el costo y la presión sobre DynamoDB en picos
  }
}

# Umbrales de la capa 1 por modelo (contratos.md §9: /arquifusion/{stage}/thresholds/{model}). Terraform solo los
# crea: los ajustes posteriores en SSM se respetan. Sin parámetro, procesar usa thresholds_default.json.
resource "aws_ssm_parameter" "thresholds" {
  for_each    = local.thresholds_by_model
  name        = "${local.ssm_prefix}/thresholds/${each.key}"
  description = "Umbrales de la capa 1 de procesar para el modelo ${each.key} (RF-02.1)"
  type        = "String"
  value       = jsonencode(each.value)

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_cloudwatch_metric_alarm" "procesar_errors" {
  alarm_name          = "${local.procesar_name}-errors"
  alarm_description   = "procesar falla invocaciones completas (Flujo G)"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.procesar.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.alarm_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "procesar_unknown_machines" {
  alarm_name          = "${local.procesar_name}-unknown-machines"
  alarm_description   = "Llegan lecturas de máquinas que no están en el seed: se descartan (#1)"
  namespace           = "ArquiFusion"
  metric_name         = "ReadingsUnknownMachine"
  dimensions          = { service = "procesar" }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.alarm_topic_arn]
}
