# infra/gcp

- **Dueño:** Persona C base (Firestore, reglas, service account) + B (Pub/Sub `notificaciones`, Cloud Function `notify_bridge`).
- **Contiene:** provider `google`: Firestore `(default)` en `nam5` con PITR (7 días) y protección de borrado, Security Rules (`firestore.rules`), índice de `users.fcm_tokens` desactivado, APIs, service account `aws-integration` para las Lambdas de AWS.
- **State:** `s3://<bucket-tfstate>/arquifusion/gcp/terraform.tfstate` (uno solo: Firestore `(default)` es único por proyecto).
- **Desplegar:** `terraform -chdir=infra/gcp init -backend-config=../backend.hcl && terraform -chdir=infra/gcp apply -var stage=<stage> -var gcp_project_id=<id>` (ver «Puesta en marcha» abajo).
  Requiere `infra/base` aplicado antes (lee el SSM `/arquifusion/<stage>/api/url` para la suscripción push).
- **`-var` obligatorios:** `gcp_project_id` y `stage` (sin default; `terraform apply` los pedirá o fallará en CI). Los demás
  (`gcp_billing`, `push_subscription`, ...) tienen default.
- **Credenciales AWS necesarias** al aplicar este stack: el provider `aws` lee SSM (`/arquifusion/<stage>/api/url`), así que
  hace falta una sesión AWS válida (Learner Lab, no expirada) además de `gcloud auth application-default login`.
  `scripts/deploy_infra.sh` **no** aplica este stack: se despliega aparte.

## Facturación: `gcp_billing` (por defecto `false`)

El proyecto puede quedar en el plan **Spark** (sin cuenta de facturación). Nada del diseño original se borra: con
`-var gcp_billing=true` se despliega exactamente el plan original.

| Pieza | `gcp_billing = false` (Spark) | `gcp_billing = true` (Blaze) |
|---|---|---|
| Firestore, reglas, Auth, FCM, Pub/Sub `notificaciones`, SA `aws-integration` | ✅ | ✅ |
| PITR de Firestore | ❌ (exige facturación; la fuente de verdad es DynamoDB con PITR y `replicar` vuelve a copiar) | ✅ 7 días |
| Push FCM (RF-10.2) | Suscripción push `notificaciones-push` → AWS `POST /bridge/push` → Lambda `notify-push` (misma lógica, `services/incidents/notify_push`) | Cloud Function `notify-push` |
| Acciones del técnico (RF-16.5) | El front llama directo a `/incidents/{id}/ack|resolve` y `/technicians/me/status` (ya lo hace) | además, Cloud Function `notify-actions` (Firestore `actions` → `/bridge/events`) |
| Secret Manager `bridge-api-key`, bucket de código, APIs de Functions/Run/Build/Eventarc/Artifact Registry | no se crean | ✅ |
| Roles extra de `aws-integration` | `firebasecloudmessaging.admin` (la Lambda envía FCM) | — |

La suscripción push firma cada entrega con un token OIDC de la SA `pubsub-push` (`aud = arquifusion-notify-push`); la
Lambda lo valida.

**Plan B** si GCP no deja crear la suscripción push sin facturación: aplicar este stack con `-var push_subscription=false`
e `infra/incidents` con `-var push_mode=direct` (notificar invoca `notify-push` directo; el push sigue llegando, solo
que sin pasar por Pub/Sub).

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

## Puesta en marcha

### 1. Proyecto GCP (consola, una vez)

1. Con tu **cuenta personal** de Google: console.cloud.google.com → Nuevo proyecto (anota el ID exacto, ej. `arquifusion-g27`).
2. **Facturación: opcional.** El equipo usa el plan Spark (sin facturación, `gcp_billing = false` en `infra/gcp`). Si algún día se vincula, crea una **alerta de presupuesto** y aplica con `-var gcp_billing=true`.
3. console.firebase.google.com → **Agregar proyecto** → elige el proyecto existente → **sin Google Analytics**.
   **No** crees Firestore desde la consola (lo crea Terraform; la ubicación es inmutable).
4. Firebase → **Authentication → Comenzar** (sin proveedores). Firebase → ⚙ Configuración → **Agregar app web** (la config pública va al `.env` del frontend).

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project arquifusion-g27
gcloud auth application-default set-quota-project arquifusion-g27
gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com
```

### 2. Terraform GCP (backend S3 compartido, `-var stage`)

⚠ El proyecto GCP es **uno solo** (Firestore `(default)` es único), así que este stack debe tener **un solo state**.
Se aplica contra el bucket de la cuenta de integración con `stage=dev`. Si lo aplicas antes desde tu lab, luego se mueve con `terraform init -migrate-state`.

```bash
export GOOGLE_BILLING_PROJECT=arquifusion-g27   # las APIs de Firebase exigen quota project
export USER_PROJECT_OVERRIDE=true
terraform -chdir=infra/gcp init -backend-config=../backend.hcl
terraform -chdir=infra/gcp validate
terraform -chdir=infra/gcp apply -var stage=dev -var gcp_project_id=arquifusion-g27
terraform -chdir=infra/gcp output
```

### 3. Llave de la service account → AWS Secrets Manager

Una llave **por cuenta AWS**, creada y subida en el mismo paso (nunca a git ni chat):

```bash
SA=$(terraform -chdir=infra/gcp output -raw aws_service_account_email)
KEY=$(mktemp -d)/sa-key.json
gcloud iam service-accounts keys create "$KEY" --iam-account="$SA"
# infra/base ya crea el secreto vacío; solo se carga el valor:
aws secretsmanager put-secret-value --secret-id arquifusion/<stage>/gcp/service-account --secret-string "file://$KEY"
rm -f "$KEY"
```
