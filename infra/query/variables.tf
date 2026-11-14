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

variable "cors_origin" {
  description = "Origen permitido del front (contratos.md §1.2): * en dev, URL de CloudFront en prod"
  type        = string
  default     = "*"
}

variable "gcp_project_id" {
  description = "Proyecto GCP de Firestore. Vacío = project_id de la llave en Secrets Manager"
  type        = string
  default     = ""
}

variable "replica_heartbeat_s" {
  description = "replicar: máximo 1 write cada N s por máquina si solo cambian campos ruidosos (0 = siempre)"
  type        = number
  default     = 300
}

variable "alarms_enabled" {
  description = "Crea alarmas hacia SNS {prefix}-platform-alarms (lo crea B en infra/base)"
  type        = bool
  default     = true
}
