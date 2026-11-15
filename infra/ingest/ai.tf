# Lambda ia-gemini: diagnóstico, resúmenes por rol, causa común, resumen del chat, reporte ejecutivo y asistente.
# Cubre: RF-02.6, RF-10.3, RF-12.3, RF-14, RF-16.8, MH-MC-03. Dueño: Persona A (worker 3).
# Fuera de la VPC (sale a generativelanguage.googleapis.com o al endpoint de Bedrock). Zip = services/ai/ia_gemini + capa común.
#
# Proveedor LLM configurable (llm_client.py): var.llm_provider = "gemini" (activo en el Learner Lab, donde LabRole
# recibe AccessDenied en Bedrock) o "bedrock" (Converse, pago por token; requiere acceso al modelo habilitado y
# bedrock:InvokeModel en el rol). El nombre `ia-gemini` se mantiene para no romper el ARN publicado en SSM.
#
# La API key de Google AI Studio NO va en Terraform. Tras el apply:
#   aws secretsmanager put-secret-value --secret-id arquifusion/<stage>/gemini/api-key --secret-string '<API_KEY>'

locals {
  ia_gemini_name = "${local.prefix}-ia-gemini"
  ia_gemini_dir  = "${path.module}/../../services/ai/ia_gemini"
  ia_gemini_files = setunion(
    setsubtract(fileset(local.ia_gemini_dir, "*.py"), ["conftest.py"]),
    fileset(local.ia_gemini_dir, "prompts/*.md"),
  )
}

variable "llm_provider" {
  description = "Cadena de proveedores LLM separados por coma: gemini,bedrock (RF-02.6, RF-14)"
  type        = string
  default     = "gemini,bedrock"
  validation {
    condition = alltrue([
      for p in split(",", var.llm_provider) : contains(["gemini", "bedrock"], trimspace(p))
    ])
    error_message = "llm_provider debe ser una lista separada por comas con gemini y/o bedrock."
  }
}

variable "gemini_model" {
  description = "Modelo de la Gemini API (baja latencia). El alias *-latest sobrevive a retiradas de versiones fijas."
  type        = string
  default     = "gemini-flash-lite-latest"
}

variable "gemini_api_base" {
  description = "Endpoint de Gemini: aistudio | vertex | auto (auto intenta AI Studio y cae a Vertex express)"
  type        = string
  default     = "auto"
  validation {
    condition     = contains(["aistudio", "vertex", "auto"], var.gemini_api_base)
    error_message = "gemini_api_base debe ser aistudio, vertex o auto."
  }
}

variable "gemini_vertex_model" {
  description = "Modelo para Vertex AI express cuando AI Studio rechaza la clave"
  type        = string
  default     = "gemini-2.5-flash-lite"
}

variable "bedrock_model_id" {
  description = "Modelo de Bedrock Converse cuando llm_provider = bedrock"
  type        = string
  default     = "amazon.nova-micro-v1:0"
}

variable "llm_timeout_s" {
  description = "Timeout por llamada al LLM. El asistente además usa un deadline global de 20 s (API Gateway corta a 29 s)"
  type        = number
  default     = 12
}

resource "aws_secretsmanager_secret" "gemini_api_key" {
  name                    = "arquifusion/${var.stage}/gemini/api-key"
  description             = "API key de Google AI Studio para ia-gemini (texto plano o JSON {\"api_key\": \"...\"})"
  recovery_window_in_days = 0
}

data "archive_file" "ia_gemini" {
  type        = "zip"
  output_path = "${path.module}/../../build/ia-gemini.zip"

  dynamic "source" {
    for_each = local.ia_gemini_files
    content {
      content  = file("${local.ia_gemini_dir}/${source.value}")
      filename = source.value
    }
  }
}

resource "aws_cloudwatch_log_group" "ia_gemini" {
  name              = "/aws/lambda/${local.ia_gemini_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "ia_gemini" {
  function_name                  = local.ia_gemini_name
  description                    = "Cliente LLM (Gemini o Bedrock) con fallback determinista (RF-02.6, RF-14)"
  role                           = local.lab_role
  runtime                        = "python3.12"
  handler                        = "handler.handler"
  filename                       = data.archive_file.ia_gemini.output_path
  source_code_hash               = data.archive_file.ia_gemini.output_base64sha256
  layers                         = [aws_lambda_layer_version.common.arn]
  memory_size                    = 512
  timeout                        = 30                                    # API Gateway corta a los 29 s; LLM_TIMEOUT_S por llamada y deadline de 20 s en el asistente
  reserved_concurrent_executions = var.reserved_concurrency["ia_gemini"] # tope AWS Academy

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = merge(local.common_env, {
      POWERTOOLS_SERVICE_NAME = "ia-gemini"
      GEMINI_SECRET_NAME      = aws_secretsmanager_secret.gemini_api_key.name
      LLM_PROVIDER            = var.llm_provider
      LLM_TIMEOUT_S           = tostring(var.llm_timeout_s)
      GEMINI_MODEL            = var.gemini_model
      GEMINI_API_BASE         = var.gemini_api_base
      GEMINI_VERTEX_MODEL     = var.gemini_vertex_model
      BEDROCK_MODEL_ID        = var.bedrock_model_id
      TABLE_MACHINES          = local.tables.machines
      TABLE_INCIDENTS         = local.tables.incidents
      TABLE_INSIGHTS          = local.tables.insights
      CORS_ORIGIN             = var.cors_origin
    })
  }

  depends_on = [aws_cloudwatch_log_group.ia_gemini]
}

# B cablea POST /assistant/chat (stage v1, sin prefijo /v1 en la ruta) a esta Lambda; el permiso vive aquí.
resource "aws_lambda_permission" "ia_gemini_apigw" {
  statement_id  = "AllowApiGatewayAssistantChat"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ia_gemini.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${data.aws_api_gateway_rest_api.api.execution_arn}/*/POST/assistant/chat"
}

resource "aws_ssm_parameter" "ia_gemini_arn" {
  name        = "${local.ssm_prefix}/lambda/ia-gemini/arn"
  description = "ARN de ia-gemini para la SFN GestionIncidente y la ruta del asistente (Persona B)"
  type        = "String"
  value       = aws_lambda_function.ia_gemini.arn
}

resource "aws_cloudwatch_metric_alarm" "ia_gemini_errors" {
  alarm_name          = "${local.ia_gemini_name}-errors"
  alarm_description   = "ia-gemini con errores no controlados (los fallos del LLM usan fallback y no cuentan)"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.ia_gemini.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [local.alarm_topic_arn]
}
