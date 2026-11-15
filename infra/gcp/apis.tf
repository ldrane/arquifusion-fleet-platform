# APIs del proyecto. C habilita la base para que B (Pub/Sub, FCM) no se bloquee en H1.
# serviceusage y cloudresourcemanager se habilitan antes con gcloud (paso 2 del runbook).
# Las de `apis_billing` solo se pueden habilitar con facturación (Blaze): se omiten con gcp_billing = false.
locals {
  apis_free = [
    "firestore.googleapis.com",       # C: réplica, chat, mapa en vivo
    "bigquery.googleapis.com",        # C: réplica DR multinube (TAREA-13, sandbox sin facturación)
    "firebase.googleapis.com",        # C: proyecto Firebase y app web
    "firebaserules.googleapis.com",   # C: Security Rules
    "identitytoolkit.googleapis.com", # C: Firebase Auth (signInWithCustomToken)
    "iam.googleapis.com",             # service accounts
    "iamcredentials.googleapis.com",
    "pubsub.googleapis.com", # B: topic notificaciones
    "fcm.googleapis.com",    # B: push (FCM HTTP v1 send)
    "logging.googleapis.com",
  ]
  apis_billing = [
    "cloudfunctions.googleapis.com", # B: Cloud Function Gen2
    "run.googleapis.com",            # B: Gen2 corre sobre Cloud Run
    "cloudbuild.googleapis.com",     # B: build de la función
    "eventarc.googleapis.com",       # B: trigger Firestore/PubSub -> función
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com", # B: API key del bridge del lado GCP
  ]
  apis = concat(local.apis_free, var.gcp_billing ? local.apis_billing : [])
}

resource "google_project_service" "apis" {
  for_each = toset(local.apis)

  service                    = each.value
  disable_on_destroy         = false # nunca apagar APIs al destruir: rompe a los otros integrantes
  disable_dependent_services = false
}
