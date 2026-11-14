# Ingesta de telemetría: POST /telemetry → SQS (integración directa, sin Lambda) + DLQ y alarmas.
# Cubre: RF-01.1, RF-01.3, RNF-07, ESC-04, MH-HA-05. Dueño: Persona A (worker 2).

data "aws_region" "current" {}

locals {
  # Stage del REST API que despliega la Persona B (contratos.md §9).
  api_stage_name = "v1"
  # Topic de alarmas de plataforma que crea infra/base (convención de nombres, contratos.md §9).
  alarm_topic_arn = "arn:aws:sns:${data.aws_region.current.name}:${local.account_id}:${local.prefix}-platform-alarms"
}

# ---------------------------------------------------------------- colas
resource "aws_sqs_queue" "ingest_dlq" {
  name                      = "${local.prefix}-ingest-dlq"
  message_retention_seconds = 1209600 # 14 días para investigar
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "ingest" {
  name                       = "${local.prefix}-ingest"
  visibility_timeout_seconds = 60 # ≥ timeout de procesar (55 s)
  message_retention_seconds  = 345600
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingest_dlq.arn
    maxReceiveCount     = 3
  })
}

# ---------------------------------------------------------------- API Gateway: POST /telemetry
resource "aws_api_gateway_resource" "telemetry" {
  rest_api_id = data.aws_api_gateway_rest_api.api.id
  parent_id   = data.aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "telemetry"
}

# JSON Schema (draft-04) de TelemetryBatch. Fuente de verdad: contracts/openapi.yaml.
resource "aws_api_gateway_model" "telemetry_batch" {
  rest_api_id  = data.aws_api_gateway_rest_api.api.id
  name         = "TelemetryBatch"
  content_type = "application/json"
  schema = jsonencode({
    "$schema"            = "http://json-schema.org/draft-04/schema#"
    type                 = "object"
    required             = ["readings"]
    additionalProperties = false
    properties = {
      readings = {
        type     = "array"
        minItems = 1
        maxItems = 100
        items = {
          type = "object"
          required = ["machine_id", "model", "type", "timestamp", "location", "operating_hours", "temperature_c",
          "vibration_mm_s", "pressure_bar", "fuel_rate_lph", "load_pct", "speed_kmh", "rpm", "state"]
          additionalProperties = false
          properties = {
            machine_id = { type = "string", pattern = "^[A-Z]{2}-[0-9]{3,4}$" }
            model      = { type = "string" }
            type       = { type = "string", enum = ["excavator", "mining_truck", "loader", "bulldozer", "drill"] }
            timestamp  = { type = "string", pattern = "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(\\.\\d+)?Z$" }
            location = {
              type     = "object"
              required = ["lat", "lon"]
              properties = {
                lat  = { type = "number", minimum = -90, maximum = 90 }
                lon  = { type = "number", minimum = -180, maximum = 180 }
                zone = { type = "string" }
              }
            }
            operating_hours = { type = "number", minimum = 0 }
            temperature_c   = { type = "number", minimum = -20, maximum = 250 }
            vibration_mm_s  = { type = "number", minimum = 0, maximum = 100 }
            pressure_bar    = { type = "number", minimum = 0, maximum = 1000 }
            fuel_rate_lph   = { type = "number", minimum = 0, maximum = 500 }
            load_pct        = { type = "number", minimum = 0, maximum = 150 }
            speed_kmh       = { type = "number", minimum = 0, maximum = 120 }
            rpm             = { type = "number", minimum = 0, maximum = 4000 }
            state           = { type = "string", enum = ["operating", "idle", "stopped", "maintenance"] }
            sim_scenario    = { type = ["string", "null"] }
          }
        }
      }
    }
  })
}

resource "aws_api_gateway_request_validator" "telemetry" {
  rest_api_id                 = data.aws_api_gateway_rest_api.api.id
  name                        = "${local.prefix}-telemetry-body"
  validate_request_body       = true
  validate_request_parameters = false
}

resource "aws_api_gateway_method" "telemetry_post" {
  rest_api_id          = data.aws_api_gateway_rest_api.api.id
  resource_id          = aws_api_gateway_resource.telemetry.id
  http_method          = "POST"
  authorization        = "NONE"
  api_key_required     = true
  request_validator_id = aws_api_gateway_request_validator.telemetry.id
  request_models       = { "application/json" = aws_api_gateway_model.telemetry_batch.name }
}

# Integración directa con SQS SendMessage usando LabRole. El cuerpo se envuelve con el correlation_id
# ($context.requestId) y la hora de recepción; el lote va url-encoded. Ver services/ingest/procesar/ingest_procesar/message.py.
resource "aws_api_gateway_integration" "telemetry_sqs" {
  rest_api_id             = data.aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_resource.telemetry.id
  http_method             = aws_api_gateway_method.telemetry_post.http_method
  type                    = "AWS"
  integration_http_method = "POST"
  uri                     = "arn:aws:apigateway:${data.aws_region.current.name}:sqs:path/${local.account_id}/${aws_sqs_queue.ingest.name}"
  credentials             = local.lab_role
  passthrough_behavior    = "NEVER"
  request_parameters = {
    "integration.request.header.Content-Type" = "'application/x-www-form-urlencoded'"
  }
  request_templates = {
    "application/json" = join("&", [
      "Action=SendMessage",
      "MessageBody={\"correlation_id\":\"$context.requestId\",\"received_at\":\"$context.requestTimeEpoch\",\"batch\":$util.urlEncode($input.json('$'))}",
      "MessageAttribute.1.Name=correlation_id",
      "MessageAttribute.1.Value.DataType=String",
      "MessageAttribute.1.Value.StringValue=$context.requestId",
    ])
  }
}

resource "aws_api_gateway_method_response" "telemetry_202" {
  rest_api_id     = data.aws_api_gateway_rest_api.api.id
  resource_id     = aws_api_gateway_resource.telemetry.id
  http_method     = aws_api_gateway_method.telemetry_post.http_method
  status_code     = "202"
  response_models = { "application/json" = "Empty" }
  response_parameters = {
    "method.response.header.X-Correlation-Id" = true
  }
}

resource "aws_api_gateway_method_response" "telemetry_500" {
  rest_api_id     = data.aws_api_gateway_rest_api.api.id
  resource_id     = aws_api_gateway_resource.telemetry.id
  http_method     = aws_api_gateway_method.telemetry_post.http_method
  status_code     = "500"
  response_models = { "application/json" = "Error" }
}

resource "aws_api_gateway_integration_response" "telemetry_ok" {
  rest_api_id       = data.aws_api_gateway_rest_api.api.id
  resource_id       = aws_api_gateway_resource.telemetry.id
  http_method       = aws_api_gateway_method.telemetry_post.http_method
  status_code       = aws_api_gateway_method_response.telemetry_202.status_code
  selection_pattern = "2\\d{2}"
  response_parameters = {
    "method.response.header.X-Correlation-Id" = "context.requestId"
  }
  response_templates = {
    "application/json" = "{\"data\":{\"accepted\":true,\"message_id\":\"$input.path('$.SendMessageResponse.SendMessageResult.MessageId')\",\"correlation_id\":\"$context.requestId\"},\"meta\":{}}"
  }
  depends_on = [aws_api_gateway_integration.telemetry_sqs]
}

resource "aws_api_gateway_integration_response" "telemetry_error" {
  rest_api_id       = data.aws_api_gateway_rest_api.api.id
  resource_id       = aws_api_gateway_resource.telemetry.id
  http_method       = aws_api_gateway_method.telemetry_post.http_method
  status_code       = aws_api_gateway_method_response.telemetry_500.status_code
  selection_pattern = "[45]\\d{2}"
  response_templates = {
    "application/json" = "{\"error\":{\"code\":\"INTERNAL\",\"message\":\"No se pudo encolar el lote\",\"details\":[]},\"correlation_id\":\"$context.requestId\"}"
  }
  depends_on = [aws_api_gateway_integration.telemetry_sqs]
}

# ---------------------------------------------------------------- identidad del simulador (API key + usage plan)
resource "aws_api_gateway_api_key" "simulator" {
  name    = "${local.prefix}-simulator-${lower(var.default_operation_id)}"
  enabled = true
}

resource "aws_api_gateway_usage_plan" "simulator" {
  name = "${local.prefix}-simulator"
  api_stages {
    api_id = data.aws_api_gateway_rest_api.api.id
    stage  = local.api_stage_name
  }
  throttle_settings {
    rate_limit  = 500
    burst_limit = 1000
  }
  quota_settings {
    limit  = 5000000
    period = "DAY"
  }
}

resource "aws_api_gateway_usage_plan_key" "simulator" {
  key_id        = aws_api_gateway_api_key.simulator.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.simulator.id
}

# ---------------------------------------------------------------- alarmas (MH-OBS-03)
resource "aws_cloudwatch_metric_alarm" "ingest_dlq_not_empty" {
  alarm_name          = "${local.prefix}-ingest-dlq-not-empty"
  alarm_description   = "Hay lotes de telemetría en la DLQ: revisar logs de procesar (RF-01.3)"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.ingest_dlq.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.alarm_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "ingest_backlog_age" {
  alarm_name          = "${local.prefix}-ingest-backlog-age"
  alarm_description   = "La lectura más antigua en cola supera 60 s: se incumple el objetivo de detección (Flujo A)"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = aws_sqs_queue.ingest.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 60
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.alarm_topic_arn]
}
