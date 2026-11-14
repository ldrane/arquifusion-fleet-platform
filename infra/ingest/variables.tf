variable "stage" {
  description = "dev (cuenta de integración) o la inicial de cada persona para su lab"
  type        = string
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

locals {
  prefix = "arquifusion-${var.stage}"
}

variable "default_operation_id" {
  description = "operation_id que usa procesar mientras haya una sola operación (contratos.md §9)"
  type        = string
  default     = "OP-01"
}

variable "image_tag" {
  description = "Tag de las imágenes ECR de procesar y retrain"
  type        = string
  default     = "latest"
}

variable "log_retention_days" {
  type    = number
  default = 7
}

variable "cors_origin" {
  description = "Origen permitido del front para las respuestas de ia-gemini por API Gateway (contratos.md §1.2)"
  type        = string
  default     = "*"
}
