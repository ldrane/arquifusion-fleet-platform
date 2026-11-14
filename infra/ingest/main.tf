# Stack de la Persona A: ingesta, detección, IA y analítica (RF-01, RF-02, RF-03, RF-04, RF-07, RF-08, RF-13, RF-14).
#
# Archivos por área (cada uno con un único dueño dentro del equipo A):
#   main.tf                      común: datos de base, nombres, artefactos (manager)
#   ingest.tf, procesar.tf,
#   heartbeat.tf, lake.tf        hot path (worker 2)
#   ai.tf, analytics.tf,
#   retrain.tf                   IA y analítica (worker 3)
#
# Los recursos de infra/base se referencian por nombre (contratos.md §9).

data "aws_caller_identity" "current" {}

data "aws_iam_role" "lab" {
  name = "LabRole"
}

locals {
  account_id = data.aws_caller_identity.current.account_id
  lab_role   = data.aws_iam_role.lab.arn
  ssm_prefix = "/arquifusion/${var.stage}"

  # Recursos de infra/base (Persona B), por convención de nombres.
  tables = {
    machines            = "${local.prefix}-machines"
    machine_state       = "${local.prefix}-machine-state"
    idempotency         = "${local.prefix}-idempotency"
    anomalies           = "${local.prefix}-anomalies"
    incidents           = "${local.prefix}-incidents"
    technicians         = "${local.prefix}-technicians"
    inventory           = "${local.prefix}-inventory"
    catalog             = "${local.prefix}-catalog"
    maintenance_records = "${local.prefix}-maintenance-records"
    insights            = "${local.prefix}-insights"
  }
  event_bus_name = "${local.prefix}-fleet-events"
  rest_api_name  = "${local.prefix}-api"

  # Variables comunes a todas las Lambdas de este stack.
  common_env = {
    STAGE                        = var.stage
    POWERTOOLS_LOG_LEVEL         = "INFO"
    POWERTOOLS_METRICS_NAMESPACE = "ArquiFusion"
  }
}

data "aws_cloudwatch_event_bus" "fleet" {
  name = local.event_bus_name
}

data "aws_api_gateway_rest_api" "api" {
  name = local.rest_api_name
}

# Bucket de artefactos: modelos ML, código de las Lambdas zip y resultados de Athena.
resource "aws_s3_bucket" "artifacts" {
  bucket        = "${local.prefix}-artifacts-${local.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "artifacts_tls" {
  bucket = aws_s3_bucket.artifacts.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.artifacts.arn, "${aws_s3_bucket.artifacts.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

# Capa con arquifusion_shared (Persona B) + arquifusion_ml (Persona A) para las Lambdas zip.
# El zip se construye con scripts/build_layer.sh antes del apply.
resource "aws_lambda_layer_version" "common" {
  layer_name          = "${local.prefix}-a-common"
  filename            = "${path.module}/../../build/layer-a-common.zip"
  source_code_hash    = try(filebase64sha256("${path.module}/../../build/layer-a-common.zip"), null)
  compatible_runtimes = ["python3.12"]
}

# Repositorio ECR para las imágenes de procesar y retrain (dependencias ML > 250 MB).
resource "aws_ecr_repository" "ml" {
  name                 = "${local.prefix}-ml"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "ml" {
  repository = aws_ecr_repository.ml.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Conservar las 5 imágenes más recientes"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 5 }
      action       = { type = "expire" }
    }]
  })
}
