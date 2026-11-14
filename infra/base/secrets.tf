# Secretos compartidos (contratos.md §9). Los valores NO se versionan en git.
#
# - gcp/service-account: llave JSON de la SA `aws-integration` (infra/gcp/iam.tf). Se crea con gcloud y se sube con
#     aws secretsmanager put-secret-value --secret-id arquifusion/<stage>/gcp/service-account --secret-string file://key.json
#   La usan replicar y firebase-token (C) y notificar → Pub/Sub (B).
# - bridge-gcp: API key de /bridge/* que usa la Cloud Function notify_bridge. Terraform guarda aquí el valor de la
#   API key que crea (api.tf) + la URL del endpoint, para copiarla a Secret Manager de GCP (infra/gcp/notify.tf).
resource "aws_secretsmanager_secret" "gcp_service_account" {
  name                    = "arquifusion/${var.stage}/gcp/service-account"
  description             = "Llave JSON de la service account aws-integration (GCP). Valor cargado a mano."
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret" "bridge_gcp" {
  name                    = "arquifusion/${var.stage}/bridge-gcp"
  description             = "API key de POST /bridge/events (Cloud Function notify_bridge → AWS)"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "bridge_gcp" {
  secret_id = aws_secretsmanager_secret.bridge_gcp.id
  secret_string = jsonencode({
    api_key = aws_api_gateway_api_key.bridge.value
    url     = "${aws_api_gateway_stage.v1.invoke_url}/bridge/events"
  })
}
