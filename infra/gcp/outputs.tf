# Publicar aquí (y en SSM /arquifusion/<stage>/...) lo que otros stacks necesitan.

output "firestore_location" {
  value = google_firestore_database.default.location_id
}

output "aws_service_account_email" {
  description = "Para: gcloud iam service-accounts keys create ... --iam-account=<este valor>"
  value       = google_service_account.aws.email
}
