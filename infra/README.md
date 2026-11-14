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
