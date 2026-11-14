# infra/gcp

- **Dueño:** Persona C base (Firestore, reglas, service account) + B (Pub/Sub `notificaciones`, Cloud Function `notify_bridge`).
- **Contiene:** provider `google`: Firestore `(default)` en `nam5` con PITR (7 días) y protección de borrado, Security Rules (`firestore.rules`), índice de `users.fcm_tokens` desactivado, APIs, service account `aws-integration` para las Lambdas de AWS.
- **State:** `s3://<bucket-tfstate>/arquifusion/gcp/terraform.tfstate` (uno solo: Firestore `(default)` es único por proyecto).
- **Desplegar:** `terraform -chdir=infra/gcp init -backend-config=../backend.hcl && terraform -chdir=infra/gcp apply -var stage=<stage> -var gcp_project_id=<id>` (runbook `docs/h0-persona-c.md` §5).

## Colecciones (contratos.md §5)

| Colección | Escribe | Lee (reglas) |
|---|---|---|
| `machines/{machine_id}` | `replicar` (service account) | todos los roles, por `location.zone` |
| `incidents/{incident_id}` (+ `messages`, `actions`) | `replicar`; chat y acciones: clientes validados | todos los roles, por `zone`; técnico solo actúa sobre los suyos (`technician_id`) |
| `technicians/{technician_id}` | `replicar` | M S A por `location.zone` (respaldo `zone`); el técnico, su propio documento |
| `users/{uid}` | **solo** `api-lectura` (`POST /auth/firebase-token`, `arrayUnion` de `fcm_tokens`) | el propio usuario; `notify_bridge` con Admin SDK |

## Credenciales

- La llave de `aws-integration` se crea con `gcloud` y se sube a AWS Secrets Manager `arquifusion/{stage}/gcp/service-account` (nunca pasa por el tfstate).
  La usan `api-lectura` (firma local del custom token + Firestore `users`), `replicar` (Firestore) y `notificar` (B, Pub/Sub).
- `ia-gemini` (A) **no** usa esta service account: usa la API key de AI Studio (`arquifusion/{stage}/gemini/api-key`, #22).
  Pedido a B/dueño de `iam.tf`: quitar `roles/aiplatform.user` de `aws_sa_roles` (mínimo privilegio, MH-SEC-07).
