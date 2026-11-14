variable "firestore_location" {
  description = "Ubicación de Firestore. nam5 = multi-región EE.UU. (suma en HA). INMUTABLE una vez creada."
  type        = string
  default     = "nam5"
}

resource "google_firestore_database" "default" {
  name        = "(default)"
  location_id = var.firestore_location
  type        = "FIRESTORE_NATIVE"

  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_ENABLED" # 7 días de PITR (rúbrica HA)
  delete_protection_state           = "DELETE_PROTECTION_ENABLED"
  deletion_policy                   = "ABANDON" # terraform destroy no borra los datos

  depends_on = [google_project_service.apis]
}

resource "google_firebaserules_ruleset" "firestore" {
  project = var.gcp_project_id

  source {
    files {
      name    = "firestore.rules"
      content = file("${path.module}/firestore.rules")
    }
  }

  depends_on = [google_firestore_database.default]

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_firebaserules_release" "firestore" {
  project      = var.gcp_project_id
  name         = "cloud.firestore" # release de la base (default)
  ruleset_name = "projects/${var.gcp_project_id}/rulesets/${google_firebaserules_ruleset.firestore.name}"

  lifecycle {
    replace_triggered_by = [google_firebaserules_ruleset.firestore]
  }
}
