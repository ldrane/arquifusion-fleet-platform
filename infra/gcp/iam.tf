# Service account que usan las Lambdas de AWS para entrar a GCP.
# Su llave JSON NO se crea con Terraform (quedaría en el tfstate): se crea con gcloud
# y se sube directo a AWS Secrets Manager (paso 6 del runbook).
resource "google_service_account" "aws" {
  account_id   = "aws-integration"
  display_name = "AWS -> GCP (ArquiFusion)"
  description  = "Usada por Lambdas de AWS: replicar y firebase-token (C), notificar (B). ia-gemini usa API key de AI Studio (no usa la SA). Llave en AWS Secrets Manager."

  depends_on = [google_project_service.apis]
}

locals {
  # Mínimo privilegio por consumidor (MH-SEC-07)
  aws_sa_roles = {
    "roles/datastore.user"   = "replicar escribe Firestore (C)"
    "roles/pubsub.publisher" = "notificar publica en topic notificaciones (B)"
  }
  # firebase-token (C6) no necesita rol: firma el custom token localmente con la llave privada.
}

resource "google_project_iam_member" "aws" {
  for_each = local.aws_sa_roles

  project = var.gcp_project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.aws.email}"
}

# ---------------------------------------------------------------- Cloud Function notify_bridge (B, notify.tf)
resource "google_service_account" "notify_bridge" {
  account_id   = "notify-bridge"
  display_name = "Cloud Function notify_bridge (ArquiFusion)"
  description  = "Pub/Sub -> FCM y Firestore actions -> AWS /bridge/events (RF-10.2, RF-16.5)"

  depends_on = [google_project_service.apis]
}

locals {
  notify_bridge_roles = {
    "roles/datastore.user"               = "lee users/{uid}.fcm_tokens y quita tokens inválidos"
    "roles/firebasecloudmessaging.admin" = "envía push FCM"
    "roles/eventarc.eventReceiver"       = "recibe eventos de Eventarc (Pub/Sub y Firestore)"
    "roles/run.invoker"                  = "Eventarc invoca la función Gen2 (Cloud Run)"
  }
}

resource "google_project_iam_member" "notify_bridge" {
  for_each = local.notify_bridge_roles

  project = var.gcp_project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.notify_bridge.email}"
}
