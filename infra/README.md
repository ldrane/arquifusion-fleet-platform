# Infraestructura (Terraform)

Orden de despliegue: `base` → `ingest` / `incidents` / `query` (en paralelo) → `gcp`.

| Stack | Dueño |
|---|---|
| `base` | B |
| `ingest` | A |
| `incidents` | B |
| `query` | C |
| `gcp` | C base + B función |

- **Rol IAM:** siempre `LabRole` (AWS Academy no permite crear roles).
- **Naming:** `arquifusion-{stage}-{nombre}`. Tags `project`, `stage`, `stack` (automáticos) + `owner`, `rf`.
- **Cuenta de integración:** `stage=dev`, solo desde `main`. Pruebas personales: `stage=<inicial>` en tu propio lab.
- Salidas compartidas entre stacks: `terraform_remote_state` o SSM `/arquifusion/<stage>/...`.
