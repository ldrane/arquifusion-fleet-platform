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

variable "gcp_project_id" {
  type = string
}

variable "gcp_region" {
  type    = string
  default = "us-central1"
}

variable "gcp_billing" {
  description = <<-EOT
    true = plan original (proyecto con facturación / Blaze): Cloud Functions notify-push y notify-actions, Secret
    Manager, bucket de código y PITR de Firestore.
    false = plan Spark sin facturación: solo Firestore (sin PITR), reglas, Auth, FCM, Pub/Sub e IAM. El push FCM lo
    hace la Lambda notify-push de AWS (suscripción push de Pub/Sub → POST /bridge/push) y las acciones del técnico
    van directo por REST (/incidents/{id}/ack|resolve, /technicians/me/status), que el front ya usa.
  EOT
  type        = bool
  default     = false
}

variable "push_subscription" {
  description = "Solo gcp_billing=false: crea la suscripción push → AWS. false = plan B (infra/incidents push_mode=direct)"
  type        = bool
  default     = true
}

variable "push_endpoint" {
  description = "Solo gcp_billing=false: URL de POST /bridge/push. Vacío = se arma con el SSM /arquifusion/<stage>/api/url de infra/base"
  type        = string
  default     = ""
}

variable "push_audience" {
  description = "Audience del token OIDC de la suscripción push (= PUSH_AUDIENCE de la Lambda notify-push)"
  type        = string
  default     = "arquifusion-notify-push"
}
