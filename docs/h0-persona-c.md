# H0 · Persona C — runbook y acuerdos con A y B

Meta: datos maestros cargados, GCP base listo y `GET /me` respondiendo con JWT.
Rutas **sin** prefijo `/v1`: el stage de API Gateway ya es `v1`, así que la URL queda `…/v1/me` (contratos.md §2).
Comandos para **bash (Git Bash)**, siempre desde la **raíz del repo**.

## 0. Herramientas (una vez)

| Herramienta | Comprobar |
|---|---|
| Python 3.12 | `python --version` |
| Terraform ≥ 1.10 | `terraform version` |
| AWS CLI v2 | `aws --version` |
| Google Cloud CLI | `gcloud --version` |

## 1. Seeds (C1) — sin AWS

```bash
python -m venv .venv
source .venv/Scripts/activate        # Git Bash en Windows
pip install -r scripts/requirements.txt -r scripts/requirements-dev.txt
python -m pytest scripts/tests -q
python scripts/seed.py export         # regenera contracts/fixtures/seed/*.json (deben quedar idénticos)
git status                            # si los JSON aparecen modificados, alguien cambió seed_data.py
```

## 2. Seeds en tu Learner Lab (stage = c)

1. Learner Lab → **Start Lab** → **AWS Details** → **Show** en AWS CLI → pega el bloque en `$HOME\.aws\credentials`.
2. `aws sts get-caller-identity` (debe salir un ARN con `voclabs`).
3. Mientras B no haya aplicado `infra/base` en tu cuenta, crea tablas temporales:

```bash
python scripts/seed.py load   --stage c --bootstrap-tables
python scripts/seed.py verify --stage c
```

4. Antes de aplicar `infra/base` de B en tu cuenta, borra las temporales:

```bash
for t in machines technicians catalog inventory warehouses notification-rules; do aws dynamodb delete-table --table-name "arquifusion-c-$t"; done
```

## 3. Seeds en la cuenta de integración (stage = dev)

Lo corre quien tenga la sesión del lab de B (B, o tú con las credenciales temporales que B comparta en el sync):

```bash
python scripts/seed.py load   --stage dev
python scripts/seed.py verify --stage dev   # "Verify OK"
```

`--force` solo si hay que resetear la flota (borra el estado que escribió `procesar`).

## 4. Proyecto GCP (consola, una vez)

1. Con tu **cuenta personal** de Google: console.cloud.google.com → Nuevo proyecto (anota el ID exacto, ej. `arquifusion-g27`).
2. Facturación → vincula la cuenta de facturación → crea una **alerta de presupuesto**.
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

## 5. Terraform GCP (C4) — convenciones de B: backend S3 compartido, `-var stage`

⚠ El proyecto GCP es **uno solo** (Firestore `(default)` es único), así que este stack debe tener **un solo state**.
Acuerdo propuesto: se aplica contra el bucket de la cuenta de integración con `stage=dev`. Si lo aplicas antes desde tu lab, luego se mueve con `terraform init -migrate-state`.

```bash
export GOOGLE_BILLING_PROJECT=arquifusion-g27   # las APIs de Firebase exigen quota project
export USER_PROJECT_OVERRIDE=true
terraform -chdir=infra/gcp init -backend-config=../backend.hcl
terraform -chdir=infra/gcp validate
terraform -chdir=infra/gcp apply -var stage=dev -var gcp_project_id=arquifusion-g27
terraform -chdir=infra/gcp output
```

## 6. Llave de la service account → AWS Secrets Manager

Una llave **por cuenta AWS**, creada y subida en el mismo paso (nunca a git ni chat):

```bash
SA=$(terraform -chdir=infra/gcp output -raw aws_service_account_email)
KEY=$(mktemp -d)/sa-key.json
gcloud iam service-accounts keys create "$KEY" --iam-account="$SA"
aws secretsmanager create-secret --name arquifusion/c/gcp/service-account --secret-string "file://$KEY"   # tu lab
# dev: B crea el recurso vacío; tú: aws secretsmanager put-secret-value --secret-id arquifusion/dev/gcp/service-account --secret-string "file://$KEY"
rm -f "$KEY"
```

## 7. api-lectura y replicar (`infra/query`)

```bash
python -m pytest services/query -q
scripts/build_query_layer.sh                       # build/layer-c-gcp.zip (google-auth)
cp infra/backend.hcl.example infra/backend.hcl     # pon el bucket de tfstate de tu lab
terraform -chdir=infra/query init -backend-config=../backend.hcl
terraform -chdir=infra/query apply -var stage=c    # -var alarms_enabled=false si aún no existe platform-alarms
aws lambda invoke --function-name arquifusion-c-api-lectura --payload fileb://contracts/fixtures/api/get_me.event.json out.json && cat out.json
```

El zip de cada Lambda incluye `services/query/common/query_common` (C) y `services/shared/arquifusion_shared` (B); Powertools llega por la layer pública y google-auth por la layer `{p}-c-gcp`.
Usuarios demo: `python scripts/cognito_users.py --stage <stage>` (con `DEMO_PASSWORD`), ver `scripts/README.md`.

## 8. Checklist de salida H0 (C)

- [ ] PR de C mergeado (seeds, fixtures, infra/gcp, infra/query, api-lectura, replicar, front).
- [ ] `seed.py verify --stage dev` → Verify OK.
- [ ] Firestore `nam5` creado y reglas publicadas.
- [ ] Secreto `arquifusion/{stage}/gcp/service-account` con valor en tu lab y en dev.
- [ ] `GET /me` 200 con ID token en dev (incluye `technician_id` para `u-tec-07`).

---

## Acuerdos que necesito de B (cerrar en el sync de H0)

1. **Claves DynamoDB**: aprobar `contracts/dynamodb.md` (pk/sk + GSIs por atributo de dominio) o decir cuáles usa; yo ajusto `KEY_SCHEMA`.
2. **Secreto vacío** en `infra/base` (el valor lo carga C por CLI, así la llave nunca entra al tfstate):
   ```hcl
   resource "aws_secretsmanager_secret" "gcp_sa" {
     name                    = "arquifusion/${var.stage}/gcp/service-account"
     recovery_window_in_days = 0 # permite recrearlo en el lab
   }
   ```
3. **Handler** `handler.handler` y zip con `arquifusion_shared` (ya hecho en `infra/query`). CORS: lo arma `shared/response.py` (B, contratos.md §1.2).
4. **Rutas de api-lectura** (lista completa en `infra/query/README.md`: `/me`, `/auth/firebase-token`, `/machines…`, `/incidents…`, …) con Cognito authorizer e integración `AWS_PROXY` al invoke ARN publicado en SSM
   `/arquifusion/{stage}/query/api_lectura_invoke_arn`. Parámetros de ruta `{machine_id}` e `{incident_id}`. El permiso de invocación ya lo crea `infra/query`.
   ```yaml
   x-amazon-apigateway-integration: { type: aws_proxy, httpMethod: POST, uri: "${api_lectura_invoke_arn}" }
   ```
5. **Cognito**: el front manda el **ID token** (el access token no trae `email` ni `custom:zone`).
   Usuarios demo con **username legible** (no email como username) para que `cognito:username` sea el `user_id` de los contratos:
   `u-op-01` (operador, norte), `u-tec-07` (tecnico, norte), `u-mant-01` (mantenimiento, `*`), `u-sup-01` (supervisor, norte), `u-adm-01` (admin, `*`), `u-ger-01` (gerencia, `*`).
   Atributos custom `custom:zone` y `custom:technician_id` (los carga `scripts/cognito_users.py`, que crea también un `u-tec-XX` por técnico del seed).
   App client con `ALLOW_USER_PASSWORD_AUTH` para probar por CLI.
6. **`POST /auth/firebase-token` es de C** (vive en `api-lectura`, decisión 2026-11-14). Claims `role`, `zone`, `technician_id` (de `custom:technician_id`); si llega `fcm_token`, `arrayUnion` en `users/{uid}.fcm_tokens[]` (lo lee `notify_bridge` de B).
7. **Firestore `incidents/{id}`** debe incluir `zone`, `status` y `assigned_technician_id` (ya están en el schema `Incident`): las reglas los leen.

## Lo que A recibe de C

- `contracts/fixtures/seed/machines.json`: los 100 `machine_id` con modelo, tipo, zona y `home_location`. El simulador debe usar **estos** IDs.
- `machine_models.json`: `nominal` (media y desviación por variable) como baseline del simulador y de las reglas.
- Prefijos: `EX` excavator · `CM` mining_truck · `CF` loader · `BD` bulldozer · `PF` drill. Zonas: norte, sur, este, oeste.
- `last_seen_at = null` en el fixture; en DynamoDB el atributo **no existe** hasta la primera lectura (el seed omite los `null`), así `attribute_exists(last_seen_at)` de heartbeat ya las ignora. Lo mismo con `open_incident_id`. `expected_interval_s = 60` (silencio a 3× = 180 s, #21).
- `ia-gemini` (A) **no** usa la service account de GCP: usa la API key de AI Studio en `arquifusion/{stage}/gemini/api-key` (#22, no requiere facturación). La service account `aws-integration` la usan solo `api-lectura` y `replicar` (C) y `notificar` (B). Pedido a B: quitar `roles/aiplatform.user` de `infra/gcp/iam.tf`.
