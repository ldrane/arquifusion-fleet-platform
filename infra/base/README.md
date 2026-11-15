# infra/base

- **Dueño:** Persona B. **Se despliega primero.**
- **Contiene:** 13 tablas DynamoDB (PITR + Streams), bus `{p}-fleet-events`, API REST `{p}-api` (stage `v1`) con authorizer
  Cognito, OPTIONS/CORS y gateway responses, Cognito User Pool (6 grupos, `custom:zone`, `custom:technician_id`),
  SNS `{p}-alerts-{rol}` + `{p}-platform-alarms`, secretos `arquifusion/{stage}/gcp/service-account` y `.../bridge-gcp`,
  API key + usage plan del puente (`/bridge/events`). Parámetros SSM en `/arquifusion/{stage}/...`.
- **State:** `s3://<bucket-tfstate>/arquifusion/base/terraform.tfstate`.
- **Desplegar:** `terraform -chdir=infra/base init -backend-config=../backend.hcl && terraform -chdir=infra/base apply -var stage=<stage>`
  - Opcionales: `-var 'alarm_emails=["equipo@x"]'`, `-var 'alert_emails={"mantenimiento|m@x"="*"}'`, `-var cors_origin=https://dxxx.cloudfront.net`.

## Orden de despliegue

`base` → `ingest` (A) → redeploy de `v1` → `incidents` (B) / `query` (C) → `gcp`. Después de que A publique `POST /telemetry`
**hay que redeployar el stage `v1`** (si no, `/telemetry` responde "Missing Authentication Token"; el deployment de base solo se
invalida con sus propias rutas):
`terraform -chdir=infra/base apply -var stage=<stage> -var api_redeploy=$(date +%s)` **más los mismos `-var` con que se aplicó base**
(`alert_emails`, `cors_origin`, ...), o vuelven a su default. `scripts/deploy_infra.sh` lo hace solo y pasa `TF_ARGS_base`.

## Cómo se enganchan las Lambdas a la API (sin depender de otros states)

Rutas **sin** prefijo `/v1` (el stage ya es `v1`): `https://{api_id}.execute-api.us-east-1.amazonaws.com/v1/me`.
Base crea **todo** el árbol de recursos, métodos e integraciones `AWS_PROXY` (`api.tf`, `local.routes`). La URI de cada
integración se arma por **nombre** de la Lambda (contratos.md §9), así base no necesita que existan todavía:

| Lambda (nombre exacto) | Dueño / stack | Rutas | Permiso que crea el dueño |
|---|---|---|---|
| `{p}-api-lectura` | C / `infra/query` | todos los `GET`, `POST /auth/firebase-token` | `lambda_permission` `…:*/*/GET/*` y `…/POST/auth/firebase-token` (ya existe) |
| `{p}-api-comandos` | B / `infra/incidents` | `POST /incidents/{incident_id}/{ack,assign,resolve}`, `PUT /technicians/me/status`, `POST /ml/retrain`, `POST /bridge/events` | `…/{api}/*/*/*` |
| `{p}-ia-gemini` | A / `infra/ingest` | `POST /assistant/chat` | `${execution_arn}/*/POST/assistant/chat` |

- Path params **siempre** `{machine_id}` e `{incident_id}` (API Gateway no admite dos nombres en el mismo nivel).
- `POST /telemetry` lo crea A en `infra/ingest` sobre la misma API (por eso base no crea `/telemetry`).
- `/bridge/events` usa API key (usage plan `{p}-bridge`, key `{p}-bridge-gcp`); el valor queda en el secreto `arquifusion/{stage}/bridge-gcp` como `{api_key, url}`.
- C publica `/arquifusion/{stage}/query/api_lectura_invoke_arn`: equivale a la URI armada por nombre; base no la lee para no obligar a desplegar `query` antes.
- Agregar una ruta = agregar la línea a `local.routes` (y el path a `paths_l1/l2/l3`) y volver a aplicar base.

## CORS (contratos.md §1.2)

`OPTIONS` MOCK en cada recurso + gateway responses (`DEFAULT_4XX/5XX`, `UNAUTHORIZED`→`UNAUTHENTICATED`, `ACCESS_DENIED`→`FORBIDDEN`,
`THROTTLED`/`QUOTA_EXCEEDED`→`RATE_LIMITED`, `MISSING_AUTHENTICATION_TOKEN`→404) con los headers CORS y el envoltorio de error.
Las respuestas de las Lambdas llevan CORS desde `arquifusion_shared.response` (`CORS_ORIGIN`).

## Salidas y SSM

| SSM `/arquifusion/{stage}/…` | Output | Uso |
|---|---|---|
| `api/id`, `api/root_resource_id`, `api/execution_arn`, `api/authorizer_id` | `api_id`, `api_execution_arn` | stacks que agregan rutas |
| `api/url` | `api_url` | `VITE_API_URL` del front, smoke |
| `cognito/user_pool_id`, `cognito/user_pool_arn`, `cognito/client_id` | `cognito_user_pool_id`, `cognito_client_id` | front, `scripts/cognito_users.py` (busca el pool `arquifusion-{stage}-users`) |
| `sns/platform_alarms_arn`, `sns/alerts_topic_arn_prefix` | `platform_alarms_topic_arn`, `sns_topic_arns` | alarmas (A, B, C), notificar |
| `events/bus_arn` | `event_bus_name`, `event_bus_arn` | |
| — | `table_names` | variables `TABLE_<NOMBRE>` (§1.1) |
