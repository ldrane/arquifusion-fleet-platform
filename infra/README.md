# Infraestructura (Terraform)

Orden real de despliegue (detalle en [`docs/RUNBOOK-DEPLOY.md`](../docs/RUNBOOK-DEPLOY.md)):
`base` → `ingest` (primero repo ECR + imágenes, luego apply completo) → redeploy del stage `v1` de base → `incidents` / `query` → `gcp`.
`frontend` es independiente y **no** va en el despliegue por defecto.

- `ingest` depende de `base` (API, tablas, bus) y no se puede aplicar de golpe en limpio: las Lambdas `procesar`/`retrain`
  usan imágenes ECR (`procesar-<tag>`, `retrain-<tag>`) que deben existir antes del apply completo.
- `incidents` y `query` leen de `base` (e `ingest` para tablas/bus); entre sí no dependen, pero después del redeploy de `v1`.
- **Redeploy por `/telemetry`:** `POST /telemetry` lo crea `ingest` sobre la API de `base`, pero el deployment de `base` solo se
  invalida con sus propias rutas. Hay que reaplicar base con `-var api_redeploy=$(date +%s)` **repitiendo los demás `-var`**
  de base (`alert_emails`, `cors_origin`, ...) o vuelven a su default. `deploy_infra.sh` lo hace con `TF_ARGS_base`.

Atajo AWS: `STAGE=dev scripts/deploy_infra.sh` (crea el bucket de tfstate y `backend.hcl`, construye layers si cambió el código,
aplica `base ingest incidents query` — con ECR/docker para `ingest` — y redeploya el stage `v1`). Requiere **docker** para `ingest`.
**`frontend` solo se despliega si se pasa explícito** (`scripts/deploy_infra.sh frontend`): CloudFront + OAC no está garantizado en
Learner Lab y un fallo abortaría la secuencia. Front: `STAGE=dev scripts/deploy_frontend.sh`.

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
