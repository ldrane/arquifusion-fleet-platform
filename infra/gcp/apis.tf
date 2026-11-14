# APIs del proyecto. C habilita la base para que B (Pub/Sub, Cloud Functions, FCM)
# no se bloqueen en H1. serviceusage y cloudresourcemanager se habilitan antes con gcloud (paso 2 del runbook).
locals {
  apis = [
    "firestore.googleapis.com",      # C: réplica, chat, mapa en vivo
    "firebase.googleapis.com",       # C: proyecto Firebase y app web
    "firebaserules.googleapis.com",  # C: Security Rules
    "identitytoolkit.googleapis.com", # C: Firebase Auth (signInWithCustomToken)
    "iam.googleapis.com",            # service accounts
    "iamcredentials.googleapis.com",
    "pubsub.googleapis.com",         # B: topic notificaciones
    "fcm.googleapis.com",            # B: push
    "cloudfunctions.googleapis.com", # B: Cloud Function Gen2
    "run.googleapis.com",            # B: Gen2 corre sobre Cloud Run
    "cloudbuild.googleapis.com",     # B: build de la función
    "eventarc.googleapis.com",       # B: trigger Firestore/PubSub -> función
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",  # B: API key del bridge del lado GCP
    "logging.googleapis.com",
    "firebasecloudmessaging.googleapis.com", # B: FCM HTTP v1 (send)
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.apis)

  service                    = each.value
  disable_on_destroy         = false # nunca apagar APIs al destruir: rompe a los otros integrantes
  disable_dependent_services = false
}
