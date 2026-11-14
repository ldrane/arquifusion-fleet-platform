# Stack query (Persona C). H0: Lambda api-lectura con GET /v1/me.

data "aws_iam_role" "lab" {
  name = "LabRole" # Learner Lab: no se pueden crear roles (W-01)
}

data "aws_caller_identity" "current" {}

# ARN de la layer pública de Powertools (python3.12 x86_64), resuelto por SSM
data "aws_ssm_parameter" "powertools" {
  name = "/aws/service/powertools/python/x86_64/python3.12/latest"
}

locals {
  api_lectura_name = "${local.prefix}-api-lectura"
  services_dir     = "${path.module}/../../services"
  api_lectura_dir  = "${local.services_dir}/query/api_lectura"
  shared_dir       = "${local.services_dir}/shared"
}

# Zip = handler.py + service.py + librería arquifusion_shared (de B). Powertools llega por la layer.
data "archive_file" "api_lectura" {
  type        = "zip"
  output_path = "${path.module}/build/api_lectura.zip"

  source {
    content  = file("${local.api_lectura_dir}/handler.py")
    filename = "handler.py"
  }
  source {
    content  = file("${local.api_lectura_dir}/service.py")
    filename = "service.py"
  }
  dynamic "source" {
    for_each = fileset(local.shared_dir, "arquifusion_shared/*.py")
    content {
      content  = file("${local.shared_dir}/${source.value}")
      filename = source.value
    }
  }
}

resource "aws_cloudwatch_log_group" "api_lectura" {
  name              = "/aws/lambda/${local.api_lectura_name}"
  retention_in_days = 7 # MH-OBS-05
}

resource "aws_lambda_function" "api_lectura" {
  function_name    = local.api_lectura_name
  description      = "GET /v1/* (C2). H0: /v1/me"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  architectures    = ["x86_64"]
  handler          = "handler.handler"
  filename         = data.archive_file.api_lectura.output_path
  source_code_hash = data.archive_file.api_lectura.output_base64sha256
  memory_size      = 256
  timeout          = 10
  layers           = [nonsensitive(data.aws_ssm_parameter.powertools.value)]

  # Fuera de VPC en H0; vpc_config se agrega si B confirma que LabRole lo permite.
  tracing_config {
    mode = "Active"
  }

  environment {
    variables = {
      STAGE                   = var.stage
      TABLE_PREFIX            = local.prefix
      POWERTOOLS_SERVICE_NAME = "api-lectura"
      POWERTOOLS_LOG_LEVEL    = "INFO"
    }
  }

  tags = { owner = "C", rf = "RF-05" }

  depends_on = [aws_cloudwatch_log_group.api_lectura]
}

# Cualquier REST API de esta cuenta puede invocarla, solo en rutas /v1/*.
# Así B integra /v1/me sin leer este state (sin dependencias circulares).
resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowApiGatewayV1"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_lectura.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "arn:aws:execute-api:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*/*/*/v1/*"
}

# B lee esto desde infra/base para la integración AWS_PROXY de /v1/me
resource "aws_ssm_parameter" "api_lectura_invoke_arn" {
  name  = "/arquifusion/${var.stage}/query/api_lectura_invoke_arn"
  type  = "String"
  value = aws_lambda_function.api_lectura.invoke_arn
}
