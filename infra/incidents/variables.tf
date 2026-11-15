variable "stage" {
  description = "dev (cuenta de integración) o la inicial de cada persona para su lab"
  type        = string
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "default_operation_id" {
  description = "Prefijo de la pk de machines (OP-01#EX-023), contratos.md §9"
  type        = string
  default     = "OP-01"
}

variable "cors_origin" {
  description = "CORS_ORIGIN de api-comandos (contratos.md §1.2)"
  type        = string
  default     = "*"
}

variable "ack_timeout_s" {
  description = "SLA de aceptación (RF-06.5) para severidad != critical. Para la demo se puede bajar a 120"
  type        = number
  default     = 1800
}

variable "ack_timeout_critical_s" {
  description = "SLA de aceptación para severidad critical"
  type        = number
  default     = 900
}

variable "resolve_timeout_s" {
  description = "Plazo de resolución antes de marcar escalated (se sigue esperando)"
  type        = number
  default     = 86400
}

variable "manual_timeout_s" {
  description = "Espera de asignación manual cuando no hay candidatos"
  type        = number
  default     = 86400
}

variable "max_escalations" {
  description = "Máximo de escalamientos automáticos por timeout antes de pedir asignación manual"
  type        = number
  default     = 2
}

variable "pubsub_topic" {
  description = "Topic de Pub/Sub (GCP) para push FCM, contratos.md §4"
  type        = string
  default     = "notificaciones"
}

variable "push_mode" {
  description = "Cómo sale el push de notificar: pubsub (topic notificaciones) o direct (invoca notify-push sin Pub/Sub)"
  type        = string
  default     = "pubsub"
  validation {
    condition     = contains(["pubsub", "direct"], var.push_mode)
    error_message = "push_mode debe ser pubsub o direct."
  }
}

variable "push_audience" {
  description = "Audience del token OIDC de la suscripción push (debe coincidir con infra/gcp var.push_audience)"
  type        = string
  default     = "arquifusion-notify-push"
}

variable "alarms_enabled" {
  description = "Crea alarmas hacia {p}-platform-alarms (requiere infra/base)"
  type        = bool
  default     = true
}

locals {
  prefix = "arquifusion-${var.stage}"
}

# Presupuesto de concurrencia (AWS Academy: <=10 Lambdas en paralelo, RNF-costo). Ver docs/concurrencia-lambda.md.
variable "reserved_concurrency" {
  description = "Concurrencia reservada por Lambda (clave = local.functions). Las SFN reintentan Lambda.TooManyRequestsException."
  type        = map(number)
  default = {
    api_comandos = 1
    incidente    = 1
    scoring      = 1
    correlacion  = 1
    notificar    = 1
    notify_push  = 1
    auditoria    = 1
  }
}
