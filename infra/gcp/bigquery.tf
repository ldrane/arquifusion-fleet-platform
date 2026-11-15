# Réplica DR multinube (TAREA-13): dataset BigQuery del lake de ArquíFusion.
# El sandbox de BigQuery no permite streaming, pero sí *load jobs* por lotes; los sube la Lambda export-gcp
# (stack query). El dataset es la memoria de Gerencia (tablero de Looker Studio) si AWS pierde el lake.

resource "google_bigquery_dataset" "lake" {
  dataset_id    = "arquifusion_${replace(var.stage, "-", "_")}"
  location      = "US"
  friendly_name = "ArquiFusion ${var.stage} (DR)"
  description   = "Réplica DR del data lake diario (daily_machine_stats), incidentes cerrados y KPIs. Escrita por la Lambda export-gcp."

  # Al destruir el stack se borran las tablas: es una réplica, la fuente de verdad es AWS.
  delete_contents_on_destroy = true

  depends_on = [google_project_service.apis]
}

# La service account aws-integration necesita escribir tablas (dataEditor) y ejecutar jobs (jobUser).
resource "google_bigquery_dataset_iam_member" "aws_data_editor" {
  dataset_id = google_bigquery_dataset.lake.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.aws.email}"
}

resource "google_project_iam_member" "aws_bigquery_job_user" {
  project = var.gcp_project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.aws.email}"
}
