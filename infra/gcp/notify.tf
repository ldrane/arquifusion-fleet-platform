# Persona B: puente de notificaciones y acciones (RF-10.2, RF-16.5, MH-MC-02; contratos.md §4, §5).
#
# - Topic Pub/Sub `notificaciones`: lo publica la Lambda notificar (AWS) con la SA `aws-integration` (pubsub.publisher).
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
  secret_id = "bridge-api-key"
  replication {
    auto {}
  }
  labels = { project = "arquifusion", owner = "b" }

  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "bridge_api_key" {
  count       = var.bridge_secret_json == "" ? 0 : 1
  secret      = google_secret_manager_secret.bridge_api_key.id
  secret_data = var.bridge_secret_json
}

resource "google_secret_manager_secret_iam_member" "notify_bridge" {
  secret_id = google_secret_manager_secret.bridge_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.notify_bridge.email}"
}

# ---------------------------------------------------------------- código de la función
resource "google_storage_bucket" "functions_src" {
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
  name   = "notify_bridge/${data.archive_file.notify_bridge.output_md5}.zip"
  bucket = google_storage_bucket.functions_src.name
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
  for_each    = local.notify_functions
  name        = "${local.prefix}-notify-${each.key}"
  location    = var.gcp_region
  description = each.value.description

  build_config {
    runtime     = "python312"
    entry_point = each.value.entry_point
    source {
      storage_source {
        bucket = google_storage_bucket.functions_src.name
        object = google_storage_bucket_object.notify_bridge.name
      }
    }
  }

  service_config {
    min_instance_count    = 0
    max_instance_count    = var.notify_max_instances
    available_memory      = "256M"
    timeout_seconds       = 30
    service_account_email = google_service_account.notify_bridge.email
    environment_variables = {
      STAGE         = var.stage
      BRIDGE_SECRET = "${google_secret_manager_secret.bridge_api_key.id}/versions/latest"
    }
  }

  dynamic "event_trigger" {
    for_each = each.key == "push" ? [1] : []
    content {
      trigger_region        = var.gcp_region
      event_type            = "google.cloud.pubsub.topic.v1.messagePublished"
      pubsub_topic          = google_pubsub_topic.notificaciones.id
      retry_policy          = "RETRY_POLICY_DO_NOT_RETRY" # un push perdido no se reintenta (evita duplicados)
      service_account_email = google_service_account.notify_bridge.email
    }
  }

  dynamic "event_trigger" {
    for_each = each.key == "actions" ? [1] : []
    content {
      trigger_region        = var.firestore_location # el trigger vive donde está la base (nam5)
      event_type            = "google.cloud.firestore.document.v1.created"
      retry_policy          = "RETRY_POLICY_RETRY" # 5xx de AWS → reintento (idempotente por event_id)
      service_account_email = google_service_account.notify_bridge.email
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

output "pubsub_topic" {
  description = "Topic que publica notificar (PUBSUB_TOPIC en infra/incidents)"
  value       = google_pubsub_topic.notificaciones.name
}

output "notify_functions" {
  value = { for k, f in google_cloudfunctions2_function.notify : k => f.name }
}
