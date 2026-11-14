variable "stage" {
  description = "dev (cuenta de integración) o la inicial de cada persona para su lab"
  type        = string
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "cors_origin" {
  description = "Origen permitido del front (contratos.md §1.2). `*` en dev; URL de CloudFront en prod"
  type        = string
  default     = "*"
}

variable "alarm_emails" {
  description = "Emails del equipo suscritos a {p}-platform-alarms"
  type        = list(string)
  default     = []
}

variable "alert_emails" {
  description = "Suscripciones email a {p}-alerts-{rol}: clave \"<rol>|<email>\", valor = zona (o \"*\" para todas)"
  type        = map(string)
  default     = {}
}

variable "api_redeploy" {
  description = "Cambiar este valor fuerza un nuevo deployment del stage v1 (p. ej. tras publicar POST /telemetry desde infra/ingest)"
  type        = string
  default     = "1"
}

variable "api_throttle_rate" {
  description = "Throttling por defecto del stage v1 (req/s)"
  type        = number
  default     = 200
}

locals {
  prefix = "arquifusion-${var.stage}"
}
