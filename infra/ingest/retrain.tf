# Workflow Reentrenamiento: entrena IsolationForest, compara con el activo y promueve por Choice.
# Cubre: RF-13.2, MH-SFN-03, MH-AI-04, TRZ-05. Dueño: Persona A (worker 3).
# Imagen (desde la raíz del repo):
#   docker build -f services/analytics/retrain/Dockerfile -t <repo>:retrain-<tag> .
# La versión activa (SSM /model/active_version) la crea el primer `Promover` o el arranque manual con
# train_local.py; Terraform no la crea para que procesar no intente cargar un modelo inexistente.

locals {
  retrain_name  = "${local.prefix}-retrain"
  promote_name  = "${local.prefix}-retrain-promote"
  retrain_image = "${aws_ecr_repository.ml.repository_url}:retrain-${var.image_tag}"
  sql_training = trimsuffix(trimprefix(jsonencode(replace(
    file("${path.module}/../../services/analytics/retrain/training.sql"),
    "operation_id = 'OP-01'", "operation_id = '${var.default_operation_id}'"
  )), "\""), "\"")
  retrain_env = merge(local.common_env, {
    ARTIFACTS_BUCKET = module.artifacts_bucket.id
    LAKE_BUCKET      = module.lake_bucket.id
    TABLE_INSIGHTS   = local.tables.insights
  })
}

resource "aws_cloudwatch_log_group" "retrain" {
  for_each          = toset([local.retrain_name, local.promote_name])
  name              = "/aws/lambda/${each.key}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "retrain" {
  function_name = local.retrain_name
  description   = "Entrena el modelo candidato de anomalías (RF-13.2)"
  role          = local.lab_role
  package_type  = "Image"
  image_uri     = local.retrain_image
  architectures = ["x86_64"]
  memory_size   = 3008
  timeout       = 900

  ephemeral_storage {
    size = 2048
  }

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = merge(local.retrain_env, { POWERTOOLS_SERVICE_NAME = "retrain" })
  }

  depends_on = [aws_cloudwatch_log_group.retrain]
}

resource "aws_lambda_function" "retrain_promote" {
  function_name = local.promote_name
  description   = "Promueve el modelo candidato: SSM active_version + insights ml_model (RF-13.2)"
  role          = local.lab_role
  package_type  = "Image"
  image_uri     = local.retrain_image
  architectures = ["x86_64"]
  memory_size   = 512
  timeout       = 60

  image_config {
    command = ["handler.promote"]
  }

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = merge(local.retrain_env, { POWERTOOLS_SERVICE_NAME = "retrain-promote" })
  }

  depends_on = [aws_cloudwatch_log_group.retrain]
}

resource "aws_cloudwatch_log_group" "sfn_reentrenamiento" {
  name              = "/aws/vendedlogs/states/${local.prefix}-reentrenamiento"
  retention_in_days = var.log_retention_days
}

resource "aws_sfn_state_machine" "reentrenamiento" {
  name     = "${local.prefix}-reentrenamiento"
  role_arn = local.lab_role
  type     = "STANDARD"
  definition = templatefile("${path.module}/../../services/analytics/sfn/reentrenamiento.asl.json", {
    active_version_param = "${local.ssm_prefix}/model/active_version"
    sql_training         = local.sql_training
    workgroup            = aws_athena_workgroup.a.name
    database             = aws_glue_catalog_database.lake.name
    fn_retrain           = aws_lambda_function.retrain.arn
    fn_promote           = aws_lambda_function.retrain_promote.arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn_reentrenamiento.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  tracing_configuration {
    enabled = true
  }
}

resource "aws_scheduler_schedule" "reentrenamiento" {
  name                         = "${local.prefix}-reentrenamiento"
  description                  = "Reentrenamiento semanal, domingo 04:00 de Lima (RF-13.2)"
  schedule_expression          = "cron(0 4 ? * SUN *)"
  schedule_expression_timezone = "America/Lima"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_sfn_state_machine.reentrenamiento.arn
    role_arn = local.lab_role
    input    = jsonencode({ trigger = "schedule" })
  }
}

resource "aws_ssm_parameter" "reentrenamiento_arn" {
  name        = "${local.ssm_prefix}/sfn/reentrenamiento/arn"
  description = "ARN de la SFN Reentrenamiento para POST /v1/ml/retrain (Persona B)"
  type        = "String"
  value       = aws_sfn_state_machine.reentrenamiento.arn
}
