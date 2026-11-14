# Stack query (Persona C): Lambdas api-lectura (GET + POST /auth/firebase-token) y replicar (Streams -> Firestore).
# RF-02.3, RF-05, RF-11, RF-15.3, RF-16, MH-HA-03. Convenciones: contratos.md §1.1 (env), §1.2 (CORS), §9 (nombres).
# Orden: infra/base (B) -> scripts/build_query_layer.sh -> este stack. Las rutas de API Gateway las cablea B (README).

data "aws_iam_role" "lab" {
  name = "LabRole" # Learner Lab: no se pueden crear roles (W-01)
}

data "aws_caller_identity" "current" {}

# ARN de la layer pública de Powertools (python3.12 x86_64), resuelto por SSM
data "aws_ssm_parameter" "powertools" {
  name = "/aws/service/powertools/python/x86_64/python3.12/latest"
}

# Tablas de infra/base (B) por nombre (contratos.md §9): solo se necesitan los ARN de los Streams.
data "aws_dynamodb_table" "replicated" {
  for_each = toset(local.replicated_tables)
  name     = "${local.prefix}-${each.value}"
}

locals {
  services_dir = "${path.module}/../../services"
  shared_dir   = "${local.services_dir}/shared"
  common_dir   = "${local.services_dir}/query/common"

  # contratos.md §1.1: TABLE_<NOMBRE> = nombre completo de la tabla
  table_suffixes = ["machines", "machine-state", "anomalies", "incidents", "technicians", "inventory", "catalog",
  "warehouses", "maintenance-records", "insights"]
  table_env = { for t in local.table_suffixes : "TABLE_${upper(replace(t, "-", "_"))}" => "${local.prefix}-${t}" }

  # contratos.md §5: tablas que se replican a Firestore
  replicated_tables = ["machines", "incidents", "technicians"]

  common_env = merge(local.table_env, {
    STAGE                = var.stage
    CORS_ORIGIN          = var.cors_origin
    DEFAULT_OPERATION_ID = "OP-01"
    FIREBASE_SECRET_NAME = "arquifusion/${var.stage}/gcp/service-account"
    GCP_PROJECT_ID       = var.gcp_project_id # vacío = project_id de la llave
    POWERTOOLS_LOG_LEVEL = "INFO"
  })

  functions = {
    api_lectura = {
      name        = "${local.prefix}-api-lectura"
      description = "GET de la API + POST /auth/firebase-token (C). RF-05, RF-11, RF-16"
      timeout     = 10
      memory      = 512
      env         = tomap({ POWERTOOLS_SERVICE_NAME = "api-lectura" })
    }
    replicar = {
      name        = "${local.prefix}-replicar"
      description = "DynamoDB Streams -> Firestore (C). RF-05, RF-15.3, MH-HA-03"
      timeout     = 60
      memory      = 256
      env         = tomap({ POWERTOOLS_SERVICE_NAME = "replicar", REPLICA_HEARTBEAT_S = tostring(var.replica_heartbeat_s) })
    }
  }
}

# --------------------------------------------------------------------------- layer google-auth
# build/layer-c-gcp.zip lo genera scripts/build_query_layer.sh (wheels manylinux, python3.12).
resource "aws_lambda_layer_version" "gcp" {
  layer_name          = "${local.prefix}-c-gcp"
  description         = "google-auth para custom tokens de Firebase y Firestore REST (C)"
  filename            = "${path.module}/../../build/layer-c-gcp.zip"
  source_code_hash    = try(filebase64sha256("${path.module}/../../build/layer-c-gcp.zip"), null)
  compatible_runtimes = ["python3.12"]
}

# --------------------------------------------------------------------------- código
# Zip = handler.py + service.py + query_common (C) + arquifusion_shared (B).
data "archive_file" "fn" {
  for_each    = local.functions
  type        = "zip"
  output_path = "${path.module}/build/${each.key}.zip"

  source {
    content  = file("${local.services_dir}/query/${each.key}/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${local.services_dir}/query/${each.key}/service.py")
    filename = "service.py"
  }
  dynamic "source" {
    for_each = fileset(local.common_dir, "query_common/*.py")
    content {
      content  = file("${local.common_dir}/${source.value}")
      filename = source.value
    }
  }
  dynamic "source" {
    for_each = fileset(local.shared_dir, "arquifusion_shared/*.py")
    content {
      content  = file("${local.shared_dir}/${source.value}")
      filename = source.value
    }
  }
}

resource "aws_cloudwatch_log_group" "fn" {
  for_each          = local.functions
  name              = "/aws/lambda/${each.value.name}"
  retention_in_days = 7 # MH-OBS-05
}

resource "aws_lambda_function" "fn" {
  for_each         = local.functions
  function_name    = each.value.name
  description      = each.value.description
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "handler.handler"
  filename         = data.archive_file.fn[each.key].output_path
  source_code_hash = data.archive_file.fn[each.key].output_base64sha256
  memory_size      = each.value.memory
  timeout          = each.value.timeout
  layers           = [nonsensitive(data.aws_ssm_parameter.powertools.value), aws_lambda_layer_version.gcp.arn]

  # Fuera de la VPC: firebase-token y replicar salen a Firestore (GCP) y la VPC no tiene NAT (contratos.md §7).
  tracing_config {
    mode = "Active"
  }

  environment {
    variables = merge(local.common_env, each.value.env)
  }

  tags = { owner = "C", rf = each.key == "replicar" ? "RF-05 RF-15" : "RF-05 RF-11 RF-16" }

  depends_on = [aws_cloudwatch_log_group.fn]
}

# --------------------------------------------------------------------------- API Gateway -> api-lectura
# Las rutas las cablea B en infra/base (AWS_PROXY al invoke ARN de SSM). Este permiso deja invocar a cualquier
# REST API de la cuenta, solo GET (cualquier recurso) y POST /auth/firebase-token. Sin dependencia circular.
resource "aws_lambda_permission" "apigw_get" {
  statement_id  = "AllowApiGatewayGet"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn["api_lectura"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "arn:aws:execute-api:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*/*/GET/*"
}

resource "aws_lambda_permission" "apigw_firebase_token" {
  statement_id  = "AllowApiGatewayFirebaseToken"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn["api_lectura"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "arn:aws:execute-api:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*/*/POST/auth/firebase-token"
}

# B lee estos parámetros desde infra/base (integración AWS_PROXY de las rutas de api-lectura).
resource "aws_ssm_parameter" "api_lectura_invoke_arn" {
  name  = "/arquifusion/${var.stage}/query/api_lectura_invoke_arn"
  type  = "String"
  value = aws_lambda_function.fn["api_lectura"].invoke_arn
}

resource "aws_ssm_parameter" "api_lectura_arn" {
  name  = "/arquifusion/${var.stage}/query/api_lectura_arn"
  type  = "String"
  value = aws_lambda_function.fn["api_lectura"].arn
}

# --------------------------------------------------------------------------- Streams -> replicar
resource "aws_sqs_queue" "replicar_dlq" {
  name                      = "${local.prefix}-replicar-dlq"
  message_retention_seconds = 1209600 # 14 días para reprocesar
  sqs_managed_sse_enabled   = true
  tags                      = { owner = "C", rf = "MH-HA-03" }
}

resource "aws_lambda_event_source_mapping" "replicar" {
  for_each          = toset(local.replicated_tables)
  function_name     = aws_lambda_function.fn["replicar"].arn
  event_source_arn  = data.aws_dynamodb_table.replicated[each.value].stream_arn
  starting_position = "LATEST"

  batch_size                         = 100
  maximum_batching_window_in_seconds = 2 # agrupa writes sin perder la sensación de tiempo real
  bisect_batch_on_function_error     = true
  maximum_retry_attempts             = 5
  maximum_record_age_in_seconds      = 3600
  parallelization_factor             = 1 # orden por documento garantizado

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.replicar_dlq.arn
    }
  }

  # #26: de incidents solo interesan los ítems META (los EVT# ni siquiera invocan la Lambda).
  dynamic "filter_criteria" {
    for_each = each.value == "incidents" ? [1] : []
    content {
      filter {
        pattern = jsonencode({ dynamodb = { Keys = { sk = { S = ["META"] } } } })
      }
    }
  }
}

# --------------------------------------------------------------------------- alarmas (MH-OBS)
data "aws_sns_topic" "platform_alarms" {
  count = var.alarms_enabled ? 1 : 0
  name  = "${local.prefix}-platform-alarms"
}

resource "aws_cloudwatch_metric_alarm" "fn_errors" {
  for_each            = { for k, v in local.functions : k => v.name if var.alarms_enabled }
  alarm_name          = "${each.value}-errors"
  alarm_description   = "Errores de ${each.value} (C)"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.fn[each.key].function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [data.aws_sns_topic.platform_alarms[0].arn]
}

resource "aws_cloudwatch_metric_alarm" "replicar_dlq" {
  count               = var.alarms_enabled ? 1 : 0
  alarm_name          = "${local.prefix}-replicar-dlq-not-empty"
  alarm_description   = "Lotes de Streams que no se pudieron replicar a Firestore (C)"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.replicar_dlq.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [data.aws_sns_topic.platform_alarms[0].arn]
}
