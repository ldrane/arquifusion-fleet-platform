# infra/query

- **Dueño:** Persona C
- **Contiene:** Lambdas `api-lectura` y `replicar`, rutas GET de API Gateway, VPC aislada (si `LabRole` lo permite).
- **State:** `s3://<bucket-tfstate>/arquifusion/query/terraform.tfstate` (un state por stack para no bloquear el lock).
- **Desplegar:** `terraform -chdir=infra/query init -backend-config=../backend.hcl && terraform -chdir=infra/query apply -var stage=<stage>`
