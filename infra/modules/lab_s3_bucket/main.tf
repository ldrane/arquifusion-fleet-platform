# Bucket S3 compatible con AWS Academy Learner Lab.
#
# Por qué no usamos `resource "aws_s3_bucket"`:
#   En el Learner Lab una SCP de la organización deniega s3:GetBucketObjectLockConfiguration al rol voclabs.
#   El proveedor AWS de Terraform llama a esa API cada vez que lee un aws_s3_bucket (al crearlo y en cada
#   refresh), así que el apply falla siempre con AccessDenied aunque el bucket se haya creado.
#
# Qué hace este módulo:
#   Crea el bucket con la AWS CLI (HeadBucket -> CreateBucket, idempotente) y expone nombre/ARN/dominio.
#   No lee ninguna configuración del bucket. La configuración (versioning, cifrado, public access block,
#   lifecycle, política) se sigue gestionando en cada stack con los recursos aws_s3_bucket_*, que solo
#   llaman a su propia API.
#
# Limitación: `terraform destroy` NO borra el bucket (no hay force_destroy). Si hace falta borrarlo:
#   aws s3 rb s3://<bucket> --force   (si tiene versioning, vaciar antes las versiones desde la consola)
#
# Requisito: AWS CLI v2 en el PATH (ya lo exige scripts/deploy_infra.sh).

terraform {
  required_version = ">= 1.10"
}

variable "name" {
  description = "Nombre global del bucket"
  type        = string
}

variable "region" {
  description = "Región donde crear el bucket"
  type        = string
}

locals {
  # us-east-1 no acepta LocationConstraint; el resto de regiones lo exige.
  location_arg = var.region == "us-east-1" ? "" : " --create-bucket-configuration LocationConstraint=${var.region}"
  cli          = "aws s3api --region ${var.region}"
}

resource "terraform_data" "this" {
  input            = var.name
  triggers_replace = [var.name, var.region]

  provisioner "local-exec" {
    # Una sola línea con `||` y `&&`: funciona igual en sh (Linux/macOS/Git Bash) y en cmd (Windows),
    # que es el intérprete por defecto de local-exec en Windows.
    # Si el bucket ya existe (p. ej. de un apply anterior que falló) no se toca.
    command = "${local.cli} head-bucket --bucket ${var.name} || ${local.cli} create-bucket --bucket ${var.name}${local.location_arg} && ${local.cli} wait bucket-exists --bucket ${var.name}"
  }
}

# Los valores se calculan sin leer el bucket. depends_on garantiza que quien los use espere a que exista.
output "id" {
  description = "Nombre del bucket (equivalente a aws_s3_bucket.id / .bucket)"
  value       = var.name
  depends_on  = [terraform_data.this]
}

output "arn" {
  value      = "arn:aws:s3:::${var.name}"
  depends_on = [terraform_data.this]
}

output "bucket_regional_domain_name" {
  value      = "${var.name}.s3.${var.region}.amazonaws.com"
  depends_on = [terraform_data.this]
}
