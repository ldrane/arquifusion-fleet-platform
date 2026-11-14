# Lambda heartbeat + Scheduler cada 5 min: detecta máquinas silenciosas y emite MachineSilent.
# Cubre: OBS-09, RF-05. Dueño: Persona A (worker 2).

locals {
  heartbeat_name = "${local.prefix}-heartbeat"
}

# Solo el código del servicio: las dependencias (shared, ml, powertools) vienen en la capa común.
data "archive_file" "heartbeat" {
  type        = "zip"
  output_path = "${path.module}/../../build/heartbeat.zip"
  source {
    content  = file("${path.module}/../../services/ingest/heartbeat/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${path.module}/../../services/ingest/heartbeat/service.py")
    filename = "service.py"
  }
}

resource "aws_cloudwatch_log_group" "heartbeat" {
  name              = "/aws/lambda/${local.heartbeat_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "heartbeat" {
  function_name    = local.heartbeat_name
  description      = "Marca máquinas silenciosas y emite MachineSilent (OBS-09)"
  role             = local.lab_role
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.heartbeat.output_path
  source_code_hash = data.archive_file.heartbeat.output_base64sha256
  layers           = [aws_lambda_layer_version.common.arn]
  memory_size      = 256
  timeout          = 120

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = merge(local.common_env, {
      POWERTOOLS_SERVICE_NAME = "heartbeat"
      TABLE_MACHINES          = local.tables.machines
      DEFAULT_INTERVAL_S      = "60"
      SILENCE_FACTOR          = "3"
    })
  }

  depends_on = [aws_cloudwatch_log_group.heartbeat]
}

resource "aws_scheduler_schedule" "heartbeat" {
  name                         = local.heartbeat_name
  description                  = "Heartbeat de la flota cada 5 minutos (OBS-09)"
  schedule_expression          = "rate(5 minutes)"
  schedule_expression_timezone = "America/Lima"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.heartbeat.arn
    role_arn = local.lab_role
    retry_policy {
      maximum_retry_attempts = 1
    }
  }
}
