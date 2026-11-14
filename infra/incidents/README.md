# infra/incidents

- **Dueño:** Persona B
- **Contiene:** SFN `GestionIncidente`, reglas EventBridge, Lambdas `api-comandos`, `scoring-tecnicos`, `correlacion-zona`, `notificar`, `auditoria`, alarmas.
- **State:** `s3://<bucket-tfstate>/arquifusion/incidents/terraform.tfstate` (un state por stack para no bloquear el lock).
- **Desplegar:** `terraform -chdir=infra/incidents init -backend-config=../backend.hcl && terraform -chdir=infra/incidents apply -var stage=<stage>`
