# API REST `{p}-api`, stage `v1` (contratos.md §2, §1.2; openapi.yaml).
#
# Rutas SIN prefijo /v1: el stage ya es `v1`, así que la URL queda `https://{id}.execute-api.{region}.amazonaws.com/v1/me`.
# B cablea todas las rutas JWT y el puente; A agrega `POST /telemetry` (API key) en infra/ingest sobre esta misma API.
#
# Las integraciones AWS_PROXY se arman POR NOMBRE de la Lambda (`{p}-api-lectura`, `{p}-api-comandos`, `{p}-ia-gemini`):
# API Gateway no exige que la Lambda exista al crear la integración, así que base se despliega primero sin depender
# del state de nadie. Cada stack dueño de la Lambda crea su `aws_lambda_permission` (ver README.md).

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  lambdas = {
    lectura  = "${local.prefix}-api-lectura"  # C (infra/query)
    comandos = "${local.prefix}-api-comandos" # B (infra/incidents)
    gemini   = "${local.prefix}-ia-gemini"    # A (infra/ingest)
  }

  # Árbol de recursos (máx. 3 niveles). `/telemetry` NO va aquí: lo crea A.
  paths_l1 = toset(["me", "auth", "machines", "incidents", "technicians", "inventory", "parts", "maintenance",
  "analytics", "reports", "ml", "assistant", "bridge"])
  paths_l2 = toset([
    "auth/firebase-token", "machines/{machine_id}", "incidents/{incident_id}", "technicians/me",
    "parts/ranking", "parts/forecast", "maintenance/plan", "analytics/fuel", "analytics/productivity",
    "analytics/kpis", "reports/latest", "ml/model", "ml/retrain", "assistant/chat", "bridge/events",
  ])
  paths_l3 = toset([
    "machines/{machine_id}/telemetry", "machines/{machine_id}/timeline", "incidents/{incident_id}/ack",
    "incidents/{incident_id}/assign", "incidents/{incident_id}/resolve", "technicians/me/status",
  ])

  # "MÉTODO ruta" => Lambda y autenticación (cognito | api_key). Fuente: tabla de contratos.md §2.
  routes = {
    "GET me"                               = { fn = "lectura", auth = "cognito" }
    "POST auth/firebase-token"             = { fn = "lectura", auth = "cognito" }
    "GET machines"                         = { fn = "lectura", auth = "cognito" }
    "GET machines/{machine_id}"            = { fn = "lectura", auth = "cognito" }
    "GET machines/{machine_id}/telemetry"  = { fn = "lectura", auth = "cognito" }
    "GET machines/{machine_id}/timeline"   = { fn = "lectura", auth = "cognito" }
    "GET incidents"                        = { fn = "lectura", auth = "cognito" }
    "GET incidents/{incident_id}"          = { fn = "lectura", auth = "cognito" }
    "POST incidents/{incident_id}/ack"     = { fn = "comandos", auth = "cognito" }
    "POST incidents/{incident_id}/assign"  = { fn = "comandos", auth = "cognito" }
    "POST incidents/{incident_id}/resolve" = { fn = "comandos", auth = "cognito" }
    "GET technicians"                      = { fn = "lectura", auth = "cognito" }
    "PUT technicians/me/status"            = { fn = "comandos", auth = "cognito" }
    "GET inventory"                        = { fn = "lectura", auth = "cognito" }
    "GET parts/ranking"                    = { fn = "lectura", auth = "cognito" }
    "GET parts/forecast"                   = { fn = "lectura", auth = "cognito" }
    "GET maintenance/plan"                 = { fn = "lectura", auth = "cognito" }
    "GET analytics/fuel"                   = { fn = "lectura", auth = "cognito" }
    "GET analytics/productivity"           = { fn = "lectura", auth = "cognito" }
    "GET analytics/kpis"                   = { fn = "lectura", auth = "cognito" }
    "GET reports/latest"                   = { fn = "lectura", auth = "cognito" }
    "GET ml/model"                         = { fn = "lectura", auth = "cognito" }
    "POST ml/retrain"                      = { fn = "comandos", auth = "cognito" }
    "POST assistant/chat"                  = { fn = "gemini", auth = "cognito" }
    "POST bridge/events"                   = { fn = "comandos", auth = "api_key" }
  }

  all_paths = setunion(local.paths_l1, local.paths_l2, local.paths_l3)

  # Headers CORS de §1.2 (valores entre comillas simples: literales de API Gateway)
  cors_headers = {
    "Access-Control-Allow-Origin"   = "'${var.cors_origin}'"
    "Access-Control-Allow-Headers"  = "'Authorization,Content-Type,X-Correlation-Id,X-Api-Key'"
    "Access-Control-Allow-Methods"  = "'GET,POST,PUT,OPTIONS'"
    "Access-Control-Expose-Headers" = "'X-Correlation-Id'"
  }
}

resource "aws_api_gateway_rest_api" "api" {
  name        = "${local.prefix}-api"
  description = "ArquiFusion Fleet Platform (contracts/openapi.yaml). Stage v1."
  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

# ---------------------------------------------------------------- recursos
resource "aws_api_gateway_resource" "l1" {
  for_each    = local.paths_l1
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = each.value
}

resource "aws_api_gateway_resource" "l2" {
  for_each    = local.paths_l2
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.l1[split("/", each.value)[0]].id
  path_part   = split("/", each.value)[1]
}

resource "aws_api_gateway_resource" "l3" {
  for_each    = local.paths_l3
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_resource.l2[join("/", slice(split("/", each.value), 0, 2))].id
  path_part   = split("/", each.value)[2]
}

locals {
  resource_ids = merge(
    { for k, r in aws_api_gateway_resource.l1 : k => r.id },
    { for k, r in aws_api_gateway_resource.l2 : k => r.id },
    { for k, r in aws_api_gateway_resource.l3 : k => r.id },
  )
}

# ---------------------------------------------------------------- authorizer Cognito
resource "aws_api_gateway_authorizer" "cognito" {
  name            = "${local.prefix}-cognito"
  rest_api_id     = aws_api_gateway_rest_api.api.id
  type            = "COGNITO_USER_POOLS"
  provider_arns   = [aws_cognito_user_pool.users.arn]
  identity_source = "method.request.header.Authorization" # ID token (trae cognito:groups y custom:*)
}

# ---------------------------------------------------------------- métodos Lambda (AWS_PROXY)
resource "aws_api_gateway_method" "route" {
  for_each         = local.routes
  rest_api_id      = aws_api_gateway_rest_api.api.id
  resource_id      = local.resource_ids[split(" ", each.key)[1]]
  http_method      = split(" ", each.key)[0]
  authorization    = each.value.auth == "cognito" ? "COGNITO_USER_POOLS" : "NONE"
  authorizer_id    = each.value.auth == "cognito" ? aws_api_gateway_authorizer.cognito.id : null
  api_key_required = each.value.auth == "api_key"
}

resource "aws_api_gateway_integration" "route" {
  for_each                = local.routes
  rest_api_id             = aws_api_gateway_rest_api.api.id
  resource_id             = aws_api_gateway_method.route[each.key].resource_id
  http_method             = aws_api_gateway_method.route[each.key].http_method
  type                    = "AWS_PROXY"
  integration_http_method = "POST"
  uri                     = "arn:aws:apigateway:${var.aws_region}:lambda:path/2015-03-31/functions/arn:aws:lambda:${var.aws_region}:${local.account_id}:function:${local.lambdas[each.value.fn]}/invocations"
}

# ---------------------------------------------------------------- CORS: OPTIONS MOCK en cada recurso (§1.2)
resource "aws_api_gateway_method" "options" {
  for_each      = local.all_paths
  rest_api_id   = aws_api_gateway_rest_api.api.id
  resource_id   = local.resource_ids[each.value]
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "options" {
  for_each          = local.all_paths
  rest_api_id       = aws_api_gateway_rest_api.api.id
  resource_id       = local.resource_ids[each.value]
  http_method       = aws_api_gateway_method.options[each.value].http_method
  type              = "MOCK"
  request_templates = { "application/json" = "{\"statusCode\": 200}" }
}

resource "aws_api_gateway_method_response" "options" {
  for_each            = local.all_paths
  rest_api_id         = aws_api_gateway_rest_api.api.id
  resource_id         = local.resource_ids[each.value]
  http_method         = aws_api_gateway_method.options[each.value].http_method
  status_code         = "200"
  response_parameters = { for h in keys(local.cors_headers) : "method.response.header.${h}" => true }
  response_models     = { "application/json" = "Empty" }
}

resource "aws_api_gateway_integration_response" "options" {
  for_each            = local.all_paths
  rest_api_id         = aws_api_gateway_rest_api.api.id
  resource_id         = local.resource_ids[each.value]
  http_method         = aws_api_gateway_method.options[each.value].http_method
  status_code         = aws_api_gateway_method_response.options[each.value].status_code
  response_parameters = { for h, v in local.cors_headers : "method.response.header.${h}" => v }
  depends_on          = [aws_api_gateway_integration.options]
}

# Gateway responses (401 del authorizer, 403, 429, 5XX…) con CORS y el envoltorio de error del contrato (§1),
# para que el front lea el error. Las específicas mapean el tipo de API Gateway al `code` del contrato.
locals {
  gateway_responses = {
    DEFAULT_4XX                  = { code = "VALIDATION_ERROR", status = null }
    DEFAULT_5XX                  = { code = "INTERNAL", status = null }
    UNAUTHORIZED                 = { code = "UNAUTHENTICATED", status = "401" }
    INVALID_API_KEY              = { code = "UNAUTHENTICATED", status = "401" }
    ACCESS_DENIED                = { code = "FORBIDDEN", status = "403" }
    MISSING_AUTHENTICATION_TOKEN = { code = "NOT_FOUND", status = "404" } # ruta inexistente
    THROTTLED                    = { code = "RATE_LIMITED", status = "429" }
    QUOTA_EXCEEDED               = { code = "RATE_LIMITED", status = "429" }
  }
}

resource "aws_api_gateway_gateway_response" "cors" {
  for_each            = local.gateway_responses
  rest_api_id         = aws_api_gateway_rest_api.api.id
  response_type       = each.key
  status_code         = each.value.status
  response_parameters = { for h, v in local.cors_headers : "gatewayresponse.header.${h}" => v }
  response_templates = {
    "application/json" = "{\"error\":{\"code\":\"${each.value.code}\",\"message\":$context.error.messageString,\"details\":[]},\"correlation_id\":\"$context.requestId\"}"
  }
}

# ---------------------------------------------------------------- deployment + stage v1
resource "aws_api_gateway_deployment" "v1" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  description = "Despliegue de rutas de base (redeploy=${var.api_redeploy})"

  triggers = {
    redeployment = sha1(jsonencode([
      local.routes,
      local.all_paths,
      local.cors_headers,
      local.gateway_responses,
      var.api_redeploy,
      aws_api_gateway_authorizer.cognito.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_api_gateway_integration.route,
    aws_api_gateway_integration_response.options,
    aws_api_gateway_gateway_response.cors,
  ]
}

# Sin access logs: exigen el rol de CloudWatch a nivel de cuenta (aws_api_gateway_account), que LabRole no garantiza.
resource "aws_api_gateway_stage" "v1" {
  rest_api_id          = aws_api_gateway_rest_api.api.id
  deployment_id        = aws_api_gateway_deployment.v1.id
  stage_name           = "v1"
  xray_tracing_enabled = true # MH-OBS: API Gateway → Lambda → Step Functions
}

resource "aws_api_gateway_method_settings" "all" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  stage_name  = aws_api_gateway_stage.v1.stage_name
  method_path = "*/*"

  settings {
    metrics_enabled        = true
    throttling_rate_limit  = var.api_throttle_rate
    throttling_burst_limit = var.api_throttle_rate * 2
  }
}

# ---------------------------------------------------------------- API key del puente GCP → AWS (/bridge/*)
# La de /telemetry (simulador) la crea A en infra/ingest con su propio usage plan.
resource "aws_api_gateway_api_key" "bridge" {
  name    = "${local.prefix}-bridge-gcp"
  enabled = true
}

resource "aws_api_gateway_usage_plan" "bridge" {
  name        = "${local.prefix}-bridge"
  description = "Cloud Function notify_bridge → POST /bridge/events (RF-16.5)"
  api_stages {
    api_id = aws_api_gateway_rest_api.api.id
    stage  = aws_api_gateway_stage.v1.stage_name
  }
  throttle_settings {
    rate_limit  = 20
    burst_limit = 40
  }
  quota_settings {
    limit  = 50000
    period = "DAY"
  }
}

resource "aws_api_gateway_usage_plan_key" "bridge" {
  key_id        = aws_api_gateway_api_key.bridge.id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.bridge.id
}
