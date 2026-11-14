# infra/ingest

- **Dueño:** Persona A
- **Contiene:** SQS ingest + DLQ, integración API GW → SQS, Lambdas `procesar`/`heartbeat`/`ia-gemini`, ECR, Firehose, S3 lake/modelos, Glue, Athena, SFN `AnalisisDiario` y `Reentrenamiento`, Scheduler.
- **State:** `s3://<bucket-tfstate>/arquifusion/ingest/terraform.tfstate` (un state por stack para no bloquear el lock).
- **Desplegar:** `terraform -chdir=infra/ingest init -backend-config=../backend.hcl && terraform -chdir=infra/ingest apply -var stage=<stage>`
