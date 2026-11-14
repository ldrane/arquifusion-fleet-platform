# infra/gcp

- **Dueño:** Persona C base + B función
- **Contiene:** Provider `google`: Firestore + rules, Pub/Sub `notificaciones`, Cloud Function `notify_bridge`, Secret Manager, service account para AWS.
- **State:** `s3://<bucket-tfstate>/arquifusion/gcp/terraform.tfstate` (un state por stack para no bloquear el lock).
- **Desplegar:** `terraform -chdir=infra/gcp init -backend-config=../backend.hcl && terraform -chdir=infra/gcp apply -var stage=<stage>`
