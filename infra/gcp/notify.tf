# Persona B: puente de notificaciones y acciones (RF-10.2, RF-16.5, MH-MC-02; contratos.md §4, §5).
#
# - Topic Pub/Sub `notificaciones`: lo publica la Lambda notificar (AWS) con la SA `aws-integration` (pubsub.publisher).
#
# gcp_billing = false (plan Spark, sin facturación):
# - Suscripción push `notificaciones-push` → AWS POST /bridge/push (Lambda notify-push, misma lógica que la función).
#   Firma con token OIDC de la SA `pubsub-push`; la Lambda valida `aud` y `email`.
# - Sin Cloud Functions, Secret Manager ni bucket. Las acciones del técnico van directo por REST.
#
# gcp_billing = true (plan original, requiere facturación):
# - Cloud Function Gen2 `notify-push` (on_notification): Pub/Sub → FCM.
# - Cloud Function Gen2 `notify-actions` (on_incident_action): Firestore incidents/{id}/actions/{event_id} → AWS /bridge/events.
# - Secret Manager `bridge-api-key`: JSON {api_key, url} copiado del secreto AWS `arquifusion/<stage>/bridge-gcp`:
#     aws secretsmanager get-secret-value --secret-id arquifusion/<stage>/bridge-gcp --query SecretString --output text \
#       | gcloud secrets versions add bridge-api-key --data-file=-
#   (o pasar -var bridge_secret_json='...' para que lo cargue Terraform).
# Sin instancias mínimas: costo 0 en reposo.

variable "bridge_secret_json" {
  description = "Opcional: valor de arquifusion/<stage>/bridge-gcp (JSON {api_key, url}). Vacío = se carga a mano con gcloud"
  type        = string
  default     = ""
  sensitive   = true
}

variable "notify_max_instances" {
  type    = number
  default = 5
}

locals {
  notify_src = "${path.module}/../../gcp/functions/notify_bridge"
}

resource "google_pubsub_topic" "notificaciones" {
  name                       = "notificaciones"
  message_retention_duration = "86400s"
  labels                     = { project = "arquifusion", owner = "b" }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret" "bridge_api_key" {
  count     = var.gcp_billing ? 1 : 0
  secret_id = "bridge-api-key"
  replication {
    auto {}
  }
  labels = { project = "arquifusion", owner = "b" }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "bridge_api_key" {
  count       = var.gcp_billing && var.bridge_secret_json != "" ? 1 : 0
  secret      = google_secret_manager_secret.bridge_api_key[0].id
  secret_data = var.bridge_secret_json
}

resource "google_secret_manager_secret_iam_member" "notify_bridge" {
  count     = var.gcp_billing ? 1 : 0
  secret_id = google_secret_manager_secret.bridge_api_key[0].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.notify_bridge[0].email}"
}

# ---------------------------------------------------------------- código de la función
resource "google_storage_bucket" "functions_src" {
  count                       = var.gcp_billing ? 1 : 0
  name                        = "${var.gcp_project_id}-${local.prefix}-fn-src"
  location                    = "US"
  uniform_bucket_level_access = true
  force_destroy               = true
  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }
}

data "archive_file" "notify_bridge" {
  type        = "zip"
  output_path = "${path.module}/build/notify_bridge.zip"
  source {
    content  = file("${local.notify_src}/main.py")
    filename = "main.py"
  }
  source {
    content  = file("${local.notify_src}/requirements.txt")
    filename = "requirements.txt"
  }
}

resource "google_storage_bucket_object" "notify_bridge" {
  count  = var.gcp_billing ? 1 : 0
  name   = "notify_bridge/${data.archive_file.notify_bridge.output_md5}.zip"
  bucket = google_storage_bucket.functions_src[0].name
  source = data.archive_file.notify_bridge.output_path
}

locals {
  notify_functions = {
    push = {
      entry_point = "on_notification"
      description = "Pub/Sub notificaciones → FCM (RF-10.2)"
    }
    actions = {
      entry_point = "on_incident_action"
      description = "Firestore incidents/{id}/actions → AWS /bridge/events (RF-16.5)"
    }
  }
}

resource "google_cloudfunctions2_function" "notify" {
  for_each    = { for k, f in local.notify_functions : k => f if var.gcp_billing }
  name        = "${local.prefix}-notify-${each.key}"
  location    = var.gcp_region
  description = each.value.description

  build_config {
    runtime     = "python312"
    entry_point = each.value.entry_point
    source {
      storage_source {
        bucket = google_storage_bucket.functions_src[0].name
        object = google_storage_bucket_object.notify_bridge[0].name
      }
    }
  }

  service_config {
    min_instance_count    = 0
    max_instance_count    = var.notify_max_instances
    available_memory      = "256M"
    timeout_seconds       = 30
    service_account_email = google_service_account.notify_bridge[0].email
    environment_variables = {
      STAGE         = var.stage
      BRIDGE_SECRET = "${google_secret_manager_secret.bridge_api_key[0].id}/versions/latest"
    }
  }

  dynamic "event_trigger" {
    for_each = each.key == "push" ? [1] : []
    content {
      trigger_region        = var.gcp_region
      event_type            = "google.cloud.pubsub.topic.v1.messagePublished"
      pubsub_topic          = google_pubsub_topic.notificaciones.id
      retry_policy          = "RETRY_POLICY_DO_NOT_RETRY" # un push perdido no se reintenta (evita duplicados)
      service_account_email = google_service_account.notify_bridge[0].email
    }
  }

  dynamic "event_trigger" {
    for_each = each.key == "actions" ? [1] : []
    content {
      trigger_region        = var.firestore_location # el trigger vive donde está la base (nam5)
      event_type            = "google.cloud.firestore.document.v1.created"
      retry_policy          = "RETRY_POLICY_RETRY" # 5xx de AWS → reintento (idempotente por event_id)
      service_account_email = google_service_account.notify_bridge[0].email
      event_filters {
        attribute = "database"
        value     = google_firestore_database.default.name
      }
      event_filters {
        attribute = "document"
        value     = "incidents/{incident_id}/actions/{event_id}"
        operator  = "match-path-pattern"
      }
    }
  }

  labels = { project = "arquifusion", owner = "b" }

  depends_on = [google_project_iam_member.notify_bridge, google_secret_manager_secret_iam_member.notify_bridge]
}

# ---------------------------------------------------------------- gcp_billing = false: suscripción push → AWS
data "google_project" "this" {}

data "aws_ssm_parameter" "api_url" {
  count = local.push_enabled && var.push_endpoint == "" ? 1 : 0
  name  = "/arquifusion/${var.stage}/api/url" # lo publica infra/base (stage v1)
}

locals {
  push_enabled = !var.gcp_billing && var.push_subscription
  push_endpoint = !local.push_enabled ? "" : (
    var.push_endpoint != "" ? var.push_endpoint : "${nonsensitive(data.aws_ssm_parameter.api_url[0].value)}/bridge/push"
  )
}

# SA con la que Pub/Sub firma el token OIDC de cada entrega (sin roles: solo identifica al emisor)
resource "google_service_account" "pubsub_push" {
  count        = local.push_enabled ? 1 : 0
  account_id   = "pubsub-push"
  display_name = "Pub/Sub push -> AWS notify-push (ArquiFusion)"
  description  = "Identidad OIDC de la suscripción notificaciones-push. La Lambda notify-push valida este email."

  depends_on = [google_project_service.apis]
}

# El agente de servicio de Pub/Sub necesita crear tokens de esa SA (automático en proyectos nuevos; se fija igual)
resource "google_service_account_iam_member" "pubsub_token_creator" {
  count              = local.push_enabled ? 1 : 0
  service_account_id = google_service_account.pubsub_push[0].name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"

  depends_on = [google_pubsub_topic.notificaciones] # el agente existe una vez usada la API
}

resource "google_pubsub_subscription" "notificaciones_push" {
  count                      = local.push_enabled ? 1 : 0
  name                       = "notificaciones-push"
  topic                      = google_pubsub_topic.notificaciones.id
  ack_deadline_seconds       = 30
  message_retention_duration = "3600s" # un push con más de 1 h ya no sirve
  labels                     = { project = "arquifusion", owner = "b" }

  push_config {
    push_endpoint = local.push_endpoint
    oidc_token {
      service_account_email = google_service_account.pubsub_push[0].email
      audience              = var.push_audience
    }
  }

  retry_policy { # solo aplica a 401/5xx: la Lambda responde 200 aunque el push falle (sin duplicados)
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }

  expiration_policy {
    ttl = "" # nunca expira por inactividad
  }

  depends_on = [google_service_account_iam_member.pubsub_token_creator]
}

output "pubsub_topic" {
  description = "Topic que publica notificar (PUBSUB_TOPIC en infra/incidents)"
  value       = google_pubsub_topic.notificaciones.name
}

output "notify_functions" {
  value = { for k, f in google_cloudfunctions2_function.notify : k => f.name }
}

output "push_subscription" {
  description = "gcp_billing=false: suscripción push → AWS notify-push"
  value       = !local.push_enabled ? null : { name = google_pubsub_subscription.notificaciones_push[0].name, endpoint = local.push_endpoint }
}
