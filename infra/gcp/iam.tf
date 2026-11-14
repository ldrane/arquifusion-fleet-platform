# Service account que usan las Lambdas de AWS para entrar a GCP.
# Su llave JSON NO se crea con Terraform (quedaría en el tfstate): se crea con gcloud
# y se sube directo a AWS Secrets Manager (paso 6 del runbook).
resource "google_service_account" "aws" {
  account_id   = "aws-integration"
  display_name = "AWS -> GCP (ArquiFusion)"
  description  = "Usada por Lambdas de AWS: replicar y firebase-token (C), notificar (B), ia-gemini (A). Llave en AWS Secrets Manager."

  depends_on = [google_project_service.apis]
}

locals {
  # Mínimo privilegio por consumidor (MH-SEC-07)
  aws_sa_roles = {
    "roles/datastore.user"   = "replicar escribe Firestore (C)"
    "roles/pubsub.publisher" = "notificar publica en topic notificaciones (B)"
    "roles/aiplatform.user"  = "ia-gemini llama a Vertex AI (A)"
  }
  # firebase-token (C6) no necesita rol: firma el custom token localmente con la llave privada.
}

resource "google_project_iam_member" "aws" {
  for_each = local.aws_sa_roles

  project = var.gcp_project_id
  role    = each.key
  member  = "serviceAccount:${google_service_account.aws.email}"
}
