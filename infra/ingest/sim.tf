# Lambda sim-driver: gemelo de flota serverless (TAREA-07).
# Imagen en el mismo repo ECR que procesar/retrain; Scheduler cada minuto; estado en SSM.
# Solo trabaja si `/arquifusion/<stage>/sim/state` tiene `enabled: true` (lo controla la consola, TAREA-08).

locals {
  sim_driver_name = "${local.prefix}-sim-driver"
}

resource "aws_ssm_parameter" "sim_state" {
  name        = "${local.ssm_prefix}/sim/state"
  description = "Estado del simulador serverless (JSON: enabled, scenario, machines, zone, ...)"
  type        = "String"
  value       = jsonencode({ enabled = false })

  lifecycle {
    ignore_changes = [value] # la consola lo escribe en caliente; Terraform no debe revertirlo
  }
}

resource "aws_cloudwatch_log_group" "sim_driver" {
  name              = "/aws/lambda/${local.sim_driver_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "sim_driver" {
  function_name                  = local.sim_driver_name
  description                    = "Simulador serverless: inyecta telemetría real en POST /telemetry (TAREA-07)"
  role                           = local.lab_role
  package_type                   = "Image"
  image_uri                      = "${aws_ecr_repository.ml.repository_url}:sim-driver-${var.image_tag}"
  timeout                        = 60
  memory_size                    = 512
  reserved_concurrent_executions = 1

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = merge(local.common_env, {
      POWERTOOLS_SERVICE_NAME = "sim-driver"
      SIM_STATE_PARAM         = aws_ssm_parameter.sim_state.name
      SIMULATOR_SEED_DIR      = "/var/task/seed"
    })
  }

  depends_on = [aws_cloudwatch_log_group.sim_driver]
}

resource "aws_scheduler_schedule" "sim_driver" {
  name                         = local.sim_driver_name
  description                  = "Tick del simulador serverless cada minuto (solo si enabled)"
  schedule_expression          = "rate(1 minute)"
  schedule_expression_timezone = "America/Lima"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.sim_driver.arn
    role_arn = local.lab_role
    retry_policy {
      maximum_retry_attempts = 1
    }
  }
}
