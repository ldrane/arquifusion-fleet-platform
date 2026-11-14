# infra/base

- **Dueño:** Persona B
- **Contiene:** Tablas DynamoDB (PITR + Streams), bus `fleet-events`, API Gateway + Cognito authorizer, Cognito User Pool (6 grupos), SNS, Secrets Manager, Layer `shared`. **Se despliega primero.**
- **State:** `s3://<bucket-tfstate>/arquifusion/base/terraform.tfstate` (un state por stack para no bloquear el lock).
- **Desplegar:** `terraform -chdir=infra/base init -backend-config=../backend.hcl && terraform -chdir=infra/base apply -var stage=<stage>`
