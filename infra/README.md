# Infraestructura (Terraform)

Orden de despliegue: `base` → `ingest` / `incidents` / `query` (en paralelo) → `gcp`. `frontend` es independiente.

Atajo AWS: `STAGE=dev scripts/deploy_infra.sh` (crea el bucket de tfstate y `backend.hcl`, construye layers, aplica en orden y redeploya el stage `v1`). Front: `STAGE=dev scripts/deploy_frontend.sh`.

| Stack | Dueño |
|---|---|
| `base` | B |
| `ingest` | A |
| `incidents` | B |
| `query` | C |
| `gcp` | C base + B función |
| `frontend` | C |

- **Rol IAM:** siempre `LabRole` (AWS Academy no permite crear roles).
- **Naming:** `arquifusion-{stage}-{nombre}`. Tags `project`, `stage`, `stack` (automáticos) + `owner`, `rf`.
- **Cuenta de integración:** `stage=dev`, solo desde `main`. Pruebas personales: `stage=<inicial>` en tu propio lab.
- Salidas compartidas entre stacks: `terraform_remote_state` o SSM `/arquifusion/<stage>/...`.

## Limitaciones del Learner Lab (leer antes de añadir recursos)

- **Buckets S3: nunca `resource "aws_s3_bucket"`.** Una SCP de AWS Academy deniega
  `s3:GetBucketObjectLockConfiguration` a `voclabs`, y el proveedor AWS la llama en cada lectura del bucket:
  el apply falla con `AccessDenied` aunque el bucket se cree. Usa el módulo
  [`modules/lab_s3_bucket`](modules/lab_s3_bucket/main.tf) (crea el bucket con la AWS CLI) y sigue configurándolo
  con `aws_s3_bucket_versioning`, `_public_access_block`, `_policy`, etc. sobre `module.<x>.id`:
  ```hcl
  module "logs_bucket" {
    source = "../modules/lab_s3_bucket"
    name   = "${local.prefix}-logs-${local.account_id}"
    region = var.aws_region
  }
  ```
  `scripts/deploy_infra.sh` se niega a desplegar si encuentra un `aws_s3_bucket`, y quita del estado (sin borrar)
  los que haya dejado un apply anterior. Si aplicas a mano con `terraform` y te sale ese error:
  `terraform -chdir=infra/<stack> state rm aws_s3_bucket.<nombre>` y vuelve a aplicar.
  Con el módulo, `terraform destroy` **no** borra el bucket (`aws s3 rb s3://<bucket> --force`).
- **IAM:** no se pueden crear roles; siempre `LabRole`.
- Si otro recurso falla con `AccessDenied ... with an explicit deny in a service control policy`, no es un
  problema de permisos de tu cuenta: hay que cambiar el código para no usar esa API, y apuntarlo aquí.
