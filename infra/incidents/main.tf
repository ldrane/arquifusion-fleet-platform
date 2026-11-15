# Stack incidents (Persona B): SFN GestionIncidente, reglas EventBridge y Lambdas
# api-comandos, scoring-tecnicos, correlacion-zona, notificar, auditoria e incidente.
# RF-06, RF-10, RF-11, RF-12, RF-16.5, RNF-15, TRZ-02, TRZ-03, MH-SFN-01.
#
# Recursos de infra/base por NOMBRE (contratos.md §9); el ARN de ia-gemini por SSM (lo publica A).

data "aws_caller_identity" "current" {}

data "aws_iam_role" "lab" {
  name = "LabRole" # Learner Lab: no se pueden crear roles
}

data "aws_ssm_parameter" "powertools" {
  name = "/aws/service/powertools/python/x86_64/python3.12/latest"
}

data "aws_ssm_parameter" "ia_gemini_arn" {
  name = "/arquifusion/${var.stage}/lambda/ia-gemini/arn"
}

data "aws_cloudwatch_event_bus" "fleet" {
  name = "${local.prefix}-fleet-events"
}

data "aws_api_gateway_rest_api" "api" {
  name = "${local.prefix}-api"
}

locals {
  account_id   = data.aws_caller_identity.current.account_id
  services_dir = "${path.module}/../../services"
  shared_dir   = "${local.services_dir}/shared"

  tables = {
    TABLE_MACHINES            = "${local.prefix}-machines"
    TABLE_MACHINE_STATE       = "${local.prefix}-machine-state"
    TABLE_IDEMPOTENCY         = "${local.prefix}-idempotency"
    TABLE_ANOMALIES           = "${local.prefix}-anomalies"
    TABLE_INCIDENTS           = "${local.prefix}-incidents"
    TABLE_TECHNICIANS         = "${local.prefix}-technicians"
    TABLE_INVENTORY           = "${local.prefix}-inventory"
    TABLE_CATALOG             = "${local.prefix}-catalog"
    TABLE_WAREHOUSES          = "${local.prefix}-warehouses"
    TABLE_NOTIFICATION_RULES  = "${local.prefix}-notification-rules"
    TABLE_AUDIT_EVENTS        = "${local.prefix}-audit-events"
    TABLE_MAINTENANCE_RECORDS = "${local.prefix}-maintenance-records"
  }

  common_env = {
    STAGE                        = var.stage
    EVENT_BUS_NAME               = data.aws_cloudwatch_event_bus.fleet.name
    DEFAULT_OPERATION_ID         = var.default_operation_id
    POWERTOOLS_LOG_LEVEL         = "INFO"
    POWERTOOLS_METRICS_NAMESPACE = "ArquiFusion"
  }

  # Lambda => carpeta, archivos propios, variables y límites. Variables solo con la convención §1.1 (#23).
  functions = {
    api_comandos = {
      name    = "${local.prefix}-api-comandos"
      dir     = "api_comandos"
      files   = ["handler.py", "service.py"]
      timeout = 10
      memory  = 256
      rf      = "RF-06.4 RF-11.1 RF-16.5"
      env = {
        TABLE_INCIDENTS           = local.tables.TABLE_INCIDENTS
        TABLE_TECHNICIANS         = local.tables.TABLE_TECHNICIANS
        TABLE_IDEMPOTENCY         = local.tables.TABLE_IDEMPOTENCY
        CORS_ORIGIN               = var.cors_origin
        RETRAIN_STATE_MACHINE_ARN = "arn:aws:states:${var.aws_region}:${local.account_id}:stateMachine:${local.prefix}-reentrenamiento"
      }
    }
    incidente = {
      name  = "${local.prefix}-incidente"
      dir   = "incidente"
      files = ["handler.py", "service.py", "chat_firestore.py"]
      # chat_mensajes lee incidents/{id}/messages de Firestore por REST (RF-15, RF-16.8): JWT con la stdlib
      extra   = { "gcp_auth.py" = "${local.services_dir}/incidents/notificar/gcp_auth.py" }
      timeout = 20
      memory  = 256
      rf      = "RF-06 RF-11.2 RF-15 RF-16.8 TRZ-03"
      env = {
        GCP_SA_SECRET_NAME        = "arquifusion/${var.stage}/gcp/service-account"
        TABLE_INCIDENTS           = local.tables.TABLE_INCIDENTS
        TABLE_MACHINES            = local.tables.TABLE_MACHINES
        TABLE_MACHINE_STATE       = local.tables.TABLE_MACHINE_STATE
        TABLE_CATALOG             = local.tables.TABLE_CATALOG
        TABLE_INVENTORY           = local.tables.TABLE_INVENTORY
        TABLE_TECHNICIANS         = local.tables.TABLE_TECHNICIANS
        TABLE_MAINTENANCE_RECORDS = local.tables.TABLE_MAINTENANCE_RECORDS
      }
    }
    scoring = {
      name    = "${local.prefix}-scoring-tecnicos"
      dir     = "scoring"
      files   = ["handler.py", "service.py"]
      timeout = 10
      memory  = 256
      rf      = "RF-06.2 RF-06.3 TRZ-03"
      env     = { TABLE_TECHNICIANS = local.tables.TABLE_TECHNICIANS }
    }
    correlacion = {
      name    = "${local.prefix}-correlacion-zona"
      dir     = "correlacion"
      files   = ["handler.py", "service.py"]
      timeout = 10
      memory  = 256
      rf      = "RF-12"
      env = {
        TABLE_ANOMALIES = local.tables.TABLE_ANOMALIES
        TABLE_INCIDENTS = local.tables.TABLE_INCIDENTS
      }
    }
    notificar = {
      name    = "${local.prefix}-notificar"
      dir     = "notificar"
      files   = ["handler.py", "service.py", "gcp_auth.py"]
      timeout = 20
      memory  = 256
      rf      = "RF-10.1 RF-10.2 RF-10.5"
      env = {
        TABLE_NOTIFICATION_RULES = local.tables.TABLE_NOTIFICATION_RULES
        TABLE_IDEMPOTENCY        = local.tables.TABLE_IDEMPOTENCY
        TABLE_INCIDENTS          = local.tables.TABLE_INCIDENTS
        TABLE_TECHNICIANS        = local.tables.TABLE_TECHNICIANS
        ALERTS_TOPIC_ARN_PREFIX  = "arn:aws:sns:${var.aws_region}:${local.account_id}:${local.prefix}-alerts-"
        GCP_SA_SECRET_NAME       = "arquifusion/${var.stage}/gcp/service-account"
        PUBSUB_TOPIC             = var.pubsub_topic
        PUSH_MODE                = var.push_mode # pubsub | direct (plan B sin Pub/Sub, ver notify_push)
        NOTIFY_PUSH_FUNCTION     = "${local.prefix}-notify-push"
      }
    }
    # Push FCM desde AWS cuando GCP no tiene facturación (infra/gcp gcp_billing=false): reemplaza a la
    # Cloud Function notify-push con la misma lógica (gcp/functions/notify_bridge/main.py va en el zip).
    notify_push = {
      name  = "${local.prefix}-notify-push"
      dir   = "notify_push"
      files = ["handler.py", "service.py", "gcp_rest.py"]
      extra = {
        "gcp_auth.py"      = "${local.services_dir}/incidents/notificar/gcp_auth.py"
        "notify_bridge.py" = "${path.module}/../../gcp/functions/notify_bridge/main.py"
      }
      timeout = 20
      memory  = 256
      rf      = "RF-10.2 MH-MC-02"
      env = {
        GCP_SA_SECRET_NAME = "arquifusion/${var.stage}/gcp/service-account"
        PUSH_AUDIENCE      = var.push_audience
      }
    }
    auditoria = {
      name    = "${local.prefix}-auditoria"
      dir     = "auditoria"
      files   = ["handler.py", "service.py"]
      timeout = 10
      memory  = 256
      rf      = "RNF-15 TRZ-02"
      env = {
        TABLE_AUDIT_EVENTS = local.tables.TABLE_AUDIT_EVENTS
        TABLE_INCIDENTS    = local.tables.TABLE_INCIDENTS
      }
    }
  }
}

# ---------------------------------------------------------------- Lambdas
# Zip = archivos del servicio (+ `extra` de otras carpetas) + librería arquifusion_shared. Powertools llega por la layer pública. Sin dependencias
# externas (notificar firma el JWT de GCP con la stdlib, gcp_auth.py).
data "archive_file" "fn" {
  for_each    = local.functions
  type        = "zip"
  output_path = "${path.module}/build/${each.key}.zip"

  dynamic "source" {
    for_each = toset(each.value.files)
    content {
      content  = file("${local.services_dir}/incidents/${each.value.dir}/${source.value}")
      filename = source.value
    }
  }
  dynamic "source" {
    for_each = try(each.value.extra, {}) # archivos de otras carpetas: nombre en el zip => ruta
    content {
      content  = file(source.value)
      filename = source.key
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
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "handler.handler"
  filename         = data.archive_file.fn[each.key].output_path
  source_code_hash = data.archive_file.fn[each.key].output_base64sha256
  memory_size      = each.value.memory
  timeout          = each.value.timeout
  layers           = [nonsensitive(data.aws_ssm_parameter.powertools.value)]

  reserved_concurrent_executions = lookup(var.reserved_concurrency, each.key, 1) # tope AWS Academy

  # Fuera de VPC: llaman a Step Functions, SNS y GCP (sin NAT).
  tracing_config {
    mode = "Active"
  }

  environment {
    variables = merge(local.common_env, each.value.env, { POWERTOOLS_SERVICE_NAME = replace(each.key, "_", "-") })
  }

  tags = { owner = "B", rf = each.value.rf }

  depends_on = [aws_cloudwatch_log_group.fn]
}

# API Gateway → api-comandos (rutas cableadas en infra/base: /incidents/*, /technicians/me/status, /ml/retrain, /bridge/events)
resource "aws_lambda_permission" "apigw_comandos" {
  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn["api_comandos"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${data.aws_api_gateway_rest_api.api.execution_arn}/*/*/*"
}

# API Gateway → notify-push (POST /bridge/push, sin authorizer: la Lambda valida el OIDC de Pub/Sub)
resource "aws_lambda_permission" "apigw_notify_push" {
  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn["notify_push"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${data.aws_api_gateway_rest_api.api.execution_arn}/*/POST/bridge/push"
}

# ---------------------------------------------------------------- Step Functions GestionIncidente (Standard)
# Standard (no Express): necesita .waitForTaskToken con esperas humanas de horas y TimeoutSeconds (RF-06.5).
resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/vendedlogs/states/${local.prefix}-gestion-incidente"
  retention_in_days = 7
}

resource "aws_sfn_state_machine" "gestion_incidente" {
  name     = "${local.prefix}-gestion-incidente"
  type     = "STANDARD"
  role_arn = data.aws_iam_role.lab.arn

  definition = templatefile("${local.services_dir}/incidents/sfn/gestion_incidente.asl.json", {
    operation_id           = var.default_operation_id
    table_machines         = local.tables.TABLE_MACHINES
    table_incidents        = local.tables.TABLE_INCIDENTS
    event_bus_name         = data.aws_cloudwatch_event_bus.fleet.name
    fn_incidente           = aws_lambda_function.fn["incidente"].arn
    fn_scoring             = aws_lambda_function.fn["scoring"].arn
    fn_correlacion         = aws_lambda_function.fn["correlacion"].arn
    fn_notificar           = aws_lambda_function.fn["notificar"].arn
    fn_ia_gemini           = nonsensitive(data.aws_ssm_parameter.ia_gemini_arn.value)
    ack_timeout_s          = var.ack_timeout_s
    ack_timeout_critical_s = var.ack_timeout_critical_s
    resolve_timeout_s      = var.resolve_timeout_s
    manual_timeout_s       = var.manual_timeout_s
    max_escalations        = var.max_escalations
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = false
    level                  = "ERROR"
  }

  tracing_configuration {
    enabled = true
  }

  tags = { owner = "B", rf = "RF-06 RF-10 RF-11 RF-12" }
}

# ---------------------------------------------------------------- EventBridge
resource "aws_sqs_queue" "events_dlq" {
  name                      = "${local.prefix}-incidents-events-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue_policy" "events_dlq" {
  queue_url = aws_sqs_queue.events_dlq.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.events_dlq.arn
      Condition = { ArnEquals = { "aws:SourceArn" = [for r in aws_cloudwatch_event_rule.rule : r.arn] } }
    }]
  })
}

locals {
  rules = {
    # AnomalyDetected (A, procesar) → SFN. procesar ya emite solo severidad ≥ medium; el filtro lo garantiza.
    anomaly = {
      description = "AnomalyDetected → GestionIncidente (RF-06)"
      pattern = {
        source        = ["arquifusion.processor"]
        "detail-type" = ["AnomalyDetected"]
        detail        = { data = { severity = ["medium", "high", "critical"] } }
      }
    }
    # MachineSilent (A, heartbeat) → SFN con severidad low (§3)
    silent = {
      description = "MachineSilent → GestionIncidente"
      pattern = {
        source        = ["arquifusion.heartbeat"]
        "detail-type" = ["MachineSilent"]
      }
    }
    # IncidentStateChanged (SFN) → notificar (§10)
    notify = {
      description = "IncidentStateChanged → notificar (RF-10)"
      pattern = {
        source        = ["arquifusion.incident"]
        "detail-type" = ["IncidentStateChanged"]
      }
    }
    # Todos los eventos de dominio → auditoria (audit-events + historial EVT#, RNF-15)
    audit = {
      description = "Eventos de dominio → auditoria (RNF-15, TRZ-02)"
      pattern = {
        source        = ["arquifusion.incident", "arquifusion.processor", "arquifusion.heartbeat"]
        "detail-type" = ["IncidentStateChanged", "AnomalyDetected", "MachineSilent"]
      }
    }
  }
}

resource "aws_cloudwatch_event_rule" "rule" {
  for_each       = local.rules
  name           = "${local.prefix}-${each.key}"
  description    = each.value.description
  event_bus_name = data.aws_cloudwatch_event_bus.fleet.name
  event_pattern  = jsonencode(each.value.pattern)
}

resource "aws_cloudwatch_event_target" "sfn" {
  for_each       = toset(["anomaly", "silent"])
  rule           = aws_cloudwatch_event_rule.rule[each.key].name
  event_bus_name = data.aws_cloudwatch_event_bus.fleet.name
  target_id      = "gestion-incidente"
  arn            = aws_sfn_state_machine.gestion_incidente.arn
  role_arn       = data.aws_iam_role.lab.arn

  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 10
  }
  dead_letter_config {
    arn = aws_sqs_queue.events_dlq.arn
  }
}

resource "aws_cloudwatch_event_target" "lambda" {
  for_each       = { notify = "notificar", audit = "auditoria" }
  rule           = aws_cloudwatch_event_rule.rule[each.key].name
  event_bus_name = data.aws_cloudwatch_event_bus.fleet.name
  target_id      = each.value
  arn            = aws_lambda_function.fn[each.value].arn

  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 5
  }
  dead_letter_config {
    arn = aws_sqs_queue.events_dlq.arn
  }
}

resource "aws_lambda_permission" "events" {
  for_each      = { notify = "notificar", audit = "auditoria" }
  statement_id  = "AllowEventBridge-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn[each.value].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.rule[each.key].arn
}

# ---------------------------------------------------------------- SSM (lo que otros stacks pueden necesitar)
resource "aws_ssm_parameter" "out" {
  for_each = {
    "sfn/gestion_incidente/arn" = aws_sfn_state_machine.gestion_incidente.arn
    "lambda/notificar/arn"      = aws_lambda_function.fn["notificar"].arn
    "lambda/api-comandos/arn"   = aws_lambda_function.fn["api_comandos"].arn
  }
  name  = "/arquifusion/${var.stage}/${each.key}"
  type  = "String"
  value = each.value
}

# ---------------------------------------------------------------- alarmas → {p}-platform-alarms (MH-OBS-03)
locals {
  alarm_topic_arn = "arn:aws:sns:${var.aws_region}:${local.account_id}:${local.prefix}-platform-alarms"
}

resource "aws_cloudwatch_metric_alarm" "fn_errors" {
  for_each            = { for k, v in local.functions : k => v.name if var.alarms_enabled }
  alarm_name          = "${each.value}-errors"
  alarm_description   = "Errores de ${each.value} (B)"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.fn[each.key].function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.alarm_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "sfn_failed" {
  count               = var.alarms_enabled ? 1 : 0
  alarm_name          = "${local.prefix}-gestion-incidente-failed"
  alarm_description   = "Ejecuciones fallidas de GestionIncidente (B)"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.gestion_incidente.arn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.alarm_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "events_dlq" {
  count               = var.alarms_enabled ? 1 : 0
  alarm_name          = "${local.prefix}-incidents-events-dlq-not-empty"
  alarm_description   = "Eventos que EventBridge no pudo entregar a la SFN / notificar / auditoria (B)"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.events_dlq.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.alarm_topic_arn]
}
