# Contratos de integración — ArquiFusion Fleet Platform

> Grupo 27 · RootAccess. Fuente de verdad técnica: `openapi.yaml` (REST). Este documento resume el resto: eventos, Firestore, Pub/Sub, invocaciones internas y recursos compartidos.
> Regla de trabajo: **si cambia un contrato, se cambia aquí primero** y recién después el código.
> Última revisión: 2026-11-14 (rama `fix/contratos`), aplica las decisiones de `docs/auditoria-integracion-datos.md` (#3, #6-#9, #11-#15, #18-#21, #23-#24, #26).

## 1. Convenciones (valen para todo)

| Tema | Regla |
|---|---|
| Formato | JSON `snake_case`. Fechas ISO 8601 UTC. Unidades en el nombre del campo (`temperature_c`, `fuel_rate_lph`). |
| IDs | Máquina `EX-023` (2 letras + número) · Técnico `TEC-07` · Usuario Cognito `u-tec-07` · Incidente `INC-<ULID>` · Almacén `WH-01` · Componente `CMP-014` · Registro de mantenimiento `MR-<ULID>`. |
| Enums | `severity`: info, low, medium, high, critical · `machine.status`: operational, stopped, maintenance, needs_intervention, silent · `incident.status`: detected, assigned, in_progress, resolved, closed · `specialty`: motor, hidraulica, electrica, neumaticos · `zone`: norte, sur, este, oeste. |
| Respuesta OK | `{ "data": ..., "meta": {...} }` |
| Respuesta error | `{ "error": { "code", "message", "details": [] }, "correlation_id" }` |
| Paginación | `?limit=` (1-100) y `?cursor=`; siguiente página en `meta.next_cursor`. |
| Trazabilidad | `X-Correlation-Id` en la request (se genera si falta). Viaja en eventos, Pub/Sub, Firestore y logs. |
| Versionado | Prefijo `/v1` en las rutas y stage `v1` en API Gateway. Los eventos llevan `version: 1`. |
| Números | Los `Decimal` de DynamoDB salen como número JSON (int si es entero), nunca como string (#25). |

**Códigos de error**

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `VALIDATION_ERROR` | JSON Schema inválido |
| 401 | `UNAUTHENTICATED` | Falta JWT o API key, o no es válida |
| 403 | `FORBIDDEN` | El grupo de Cognito no tiene permiso, o el técnico actúa sobre un incidente que no es suyo |
| 404 | `NOT_FOUND` | No existe el recurso |
| 409 | `INCIDENT_STATE_INVALID` / `DUPLICATE_EVENT` | Ack sobre un incidente ya aceptado, o evento repetido |
| 429 | `RATE_LIMITED` | Usage plan agotado |
| 503 | `UPSTREAM_UNAVAILABLE` | Falla GCP/Gemini sin respuesta de respaldo |
| 500 | `INTERNAL` | Error no controlado |

### 1.1 Variables de entorno (una sola convención, #23)

Todas las Lambdas usan **estos nombres exactos**. El valor es el **nombre completo** del recurso (no un prefijo). Prohibidos `TABLE_PREFIX`, `INCIDENTS_TABLE`, `TECHNICIANS_TABLE` y similares.

| Variable | Valor (stage `dev`) |
|---|---|
| `STAGE` | `dev` |
| `EVENT_BUS_NAME` | `arquifusion-dev-fleet-events` |
| `TABLE_MACHINES` | `arquifusion-dev-machines` |
| `TABLE_MACHINE_STATE` | `arquifusion-dev-machine-state` |
| `TABLE_IDEMPOTENCY` | `arquifusion-dev-idempotency` |
| `TABLE_ANOMALIES` | `arquifusion-dev-anomalies` |
| `TABLE_INCIDENTS` | `arquifusion-dev-incidents` |
| `TABLE_TECHNICIANS` | `arquifusion-dev-technicians` |
| `TABLE_INVENTORY` | `arquifusion-dev-inventory` |
| `TABLE_CATALOG` | `arquifusion-dev-catalog` |
| `TABLE_WAREHOUSES` | `arquifusion-dev-warehouses` |
| `TABLE_NOTIFICATION_RULES` | `arquifusion-dev-notification-rules` |
| `TABLE_AUDIT_EVENTS` | `arquifusion-dev-audit-events` |
| `TABLE_MAINTENANCE_RECORDS` | `arquifusion-dev-maintenance-records` |
| `TABLE_INSIGHTS` | `arquifusion-dev-insights` |
| `CORS_ORIGIN` | Origen permitido del front (`*` en dev; URL de CloudFront en prod) |
| `DEFAULT_OPERATION_ID` | `OP-01` |

Regla: `TABLE_<NOMBRE>` = sufijo de la tabla en mayúsculas con `_` en lugar de `-`. Las variables propias de un servicio (`GEMINI_SECRET_NAME`, `IA_GEMINI_FUNCTION`, `STATE_MACHINE_ARN`, `FIREBASE_SECRET_NAME`, …) se mantienen, pero ninguna puede duplicar una de esta tabla. `arquifusion_shared` expone el helper para leerlas.

### 1.2 CORS (#5)

Toda respuesta de `/v1/*` (éxito **y** error, incluidas las *gateway responses* 4XX/5XX de API Gateway, para que el front pueda leer un 401) lleva:

| Header | Valor |
|---|---|
| `Access-Control-Allow-Origin` | valor de `CORS_ORIGIN` |
| `Access-Control-Allow-Headers` | `Authorization,Content-Type,X-Correlation-Id,X-Api-Key` |
| `Access-Control-Allow-Methods` | `GET,POST,PUT,OPTIONS` |
| `Access-Control-Expose-Headers` | `X-Correlation-Id` |

Cada recurso de `/v1/*` tiene método `OPTIONS` (integración MOCK, sin Lambda, sin auth) que devuelve 200 con los mismos headers. Lo arma `arquifusion_shared.response._resp`; nadie agrega headers CORS a mano.

## 2. Endpoints (26 operaciones, 3 familias)

Autenticación: **K** = API key · **J** = JWT Cognito. Roles: **O**perador, **T**écnico, **M**antenimiento, **S**upervisor, **A**dmin, **G**erencia.
Lambdas: `api-lectura` (dueña C, `services/query/api_lectura`) · `api-comandos` (dueño B, `services/incidents/api_comandos`; antes `api-ack`) · `ia-gemini` (dueño A).

| Método y ruta | Auth | Roles | Lambda | Cubre |
|---|---|---|---|---|
| `POST /telemetry` | K | simulador | — (APIGW → SQS) | RF-01 |
| `GET /v1/me` | J | todos | api-lectura | RNF-08 |
| `POST /v1/auth/firebase-token` | J | todos | **api-lectura (C)** | RF-16, MH-SEC-07 |
| `GET /v1/machines` | J | todos | api-lectura | RF-05 |
| `GET /v1/machines/{id}` | J | todos | api-lectura | RF-02, RNF-13 |
| `GET /v1/machines/{id}/telemetry` | J | T M S A G | api-lectura | RF-02.3 |
| `GET /v1/machines/{id}/timeline` | J | T M S A G | api-lectura | RF-11.4 |
| `GET /v1/incidents` | J | todos | api-lectura | RF-11 |
| `GET /v1/incidents/{id}` | J | todos | api-lectura | RF-11, RF-12 |
| `POST /v1/incidents/{id}/ack` | J | T M | api-comandos | RF-06.4, RF-10.4 |
| `POST /v1/incidents/{id}/assign` | J | M S A | api-comandos | RF-06.4 |
| `POST /v1/incidents/{id}/resolve` | J | T M | api-comandos | RF-11.1 |
| `GET /v1/technicians` | J | M S A | api-lectura | RF-05.3, RF-06.1 |
| `PUT /v1/technicians/me/status` | J | T | api-comandos | RF-06.1 |
| `GET /v1/inventory` | J | M S A | api-lectura | RF-04.2, RF-04.6 |
| `GET /v1/parts/ranking` | J | M S A | api-lectura | RF-04.3 |
| `GET /v1/parts/forecast` | J | M A | api-lectura | RF-04.4 |
| `GET /v1/maintenance/plan` | J | M S A | api-lectura | RF-03 |
| `GET /v1/analytics/fuel` | J | S A G | api-lectura | RF-07 |
| `GET /v1/analytics/productivity` | J | S A G | api-lectura | RF-08 |
| `GET /v1/analytics/kpis` | J | S A G | api-lectura | RF-11.4 |
| `GET /v1/reports/latest` | J | A G S | api-lectura | RF-10.3, RF-13.3 |
| `GET /v1/ml/model` | J | A M | api-lectura | MH-AI-04 |
| `POST /v1/ml/retrain` | J | A | api-comandos | RF-13.2 |
| `POST /v1/assistant/chat` | J | T M S A G | ia-gemini | RF-14 |
| `POST /bridge/events` | K | GCP | api-comandos | RF-16, MH-MC-02 |

`POST /v1/auth/firebase-token` vive en `api-lectura` (decisión 2026-11-14): firma el custom token con la service account de Firebase leída de Secrets Manager (`FIREBASE_SECRET_NAME`; la firma es local, no necesita salir a Internet, pero sí alcanzar Secrets Manager: fuera de VPC o con VPC endpoint).

Lo que **no** es endpoint, a propósito: chat del incidente, mapa en tiempo real y adjuntos (van por Firestore y Cloud Storage con el SDK), asignación automática y notificaciones (las hace Step Functions).

**URL base:** `https://{apiId}.execute-api.us-east-1.amazonaws.com/v1` (stage `v1`). Las rutas ya incluyen `/v1`, así que la URL completa queda `…/v1/v1/me`. El front configura `VITE_API_URL` con la URL base (incluye el stage).

### 2.1 Identidad del usuario (Cognito → Lambda → Firebase) (#8)

| Claim del ID token (Cognito) | Ejemplo | Uso |
|---|---|---|
| `cognito:username` | `u-tec-07` | `user_id` en toda la plataforma; `uid` de Firebase; `technicians.user_id` |
| `cognito:groups` | `tecnico` | Rol (RBAC). Si trae varios, gana el de mayor precedencia (`rbac.py`) |
| `custom:zone` | `norte` · `*` | Zona del usuario; `*` o ausente = todas (roles globales) |
| `custom:technician_id` | `TEC-07` | **Solo usuarios del grupo `tecnico`.** Identifica al técnico en `api-comandos` (`me/status`, ack/resolve propios) y en el custom token |

- Atributos custom del User Pool (B, `infra/base`): `custom:zone` y `custom:technician_id` (string, mutables, legibles por el app client). Los usuarios demo `u-tec-XX` se crean con `custom:technician_id = TEC-XX` y `custom:zone` = zona del técnico en el seed.
- Nadie deriva el técnico desde `cognito:username` → `technicians.user_id`: se usa el claim. (`technicians.user_id` se mantiene para ir del técnico al usuario, por ejemplo para notificar.)
- **Custom token de Firebase** (`POST /v1/auth/firebase-token`): `uid` = `cognito:username`; claims `role` (rol resuelto), `zone` (`null` si es global), `technician_id` (solo técnicos; `null` en otro caso).
- Fixtures: `fixtures/api/get_me.event.json` (técnico TEC-07, GET) y `fixtures/api/technician_status.event.json` (técnico TEC-07, PUT).

## 3. Eventos (EventBridge, bus `arquifusion-{stage}-fleet-events`)

Bus real: `arquifusion-{stage}-fleet-events` (en dev: `arquifusion-dev-fleet-events`). Las Lambdas lo leen de `EVENT_BUS_NAME`. Las fixtures `events/*.json` usan el nombre de dev.

Envoltorio común (`detail`): `{ "event_id", "correlation_id", "occurred_at", "version": 1, "data": {...} }`

| `source` → `detail-type` | Lo emite | Lo consume | `data` |
|---|---|---|---|
| `arquifusion.processor` → **AnomalyDetected** | Lambda procesar (A) | Regla → Step Functions `GestionIncidente` | `machine_id`, `zone`, `severity`, `anomaly_score`, `top_factors[]`, `health_score`, `model_version`, `reading_ts` |
| `arquifusion.heartbeat` → **MachineSilent** | Lambda heartbeat (A) | Regla → `GestionIncidente` (severidad `low`) | `machine_id`, `zone`, `last_seen_at`, `expected_interval_s`, `silence_threshold_s` |
| `arquifusion.incident` → **IncidentStateChanged** | Step Functions (B) | Lambda notificar / auditoría | `incident_id`, `from`, `to`, `event_type`, `actor{type, user_id, role}`, `machine_id`, `zone`, `severity`, `technician_id?` |

- Regla de costo: `AnomalyDetected` se emite **solo si no hay un incidente abierto para esa máquina** (escritura condicional en DynamoDB, §9). Así no se lanza una ejecución por cada lectura.
- **Heartbeat (#21):** `expected_interval_s = 60` en el seed (el simulador envía cada 60 s). Silencio = `silence_threshold_s` = 3 × `expected_interval_s` = 180 s (`SILENCE_FACTOR=3`). `MachineSilent` **no** pasa por el lock `open_incident_id` de `procesar`: la SFN deduplica (si la máquina ya tiene `open_incident_id`, no crea otro incidente).
- `IncidentStateChanged.actor`: `{ "type": "system" | "user", "user_id": "u-tec-07" | null, "role": "tecnico" | null }` (TRZ-02, #17). `event_type` sale de la tabla del §10.

## 4. Mensaje Pub/Sub (AWS → GCP, topic `notificaciones`) (#15)

Se mantiene el puente: la Lambda *notificar* (B) publica por REST al topic **`notificaciones`** (proyecto GCP con facturación) y la Cloud Function **`notify_bridge`** (`gcp/functions/notify_bridge`, trigger Pub/Sub) lo convierte en push FCM. Fixture: `fixtures/pubsub/notificacion.json`.

```json
{
  "notification_id": "ntf-01JC8Z",
  "correlation_id": "7c1e4b1a-0d2f-4a55-9c50-3b3f0a6f1e11",
  "event_type": "incident.assigned",
  "incident_id": "INC-01JC8ZK",
  "machine_id": "EX-023",
  "zone": "norte",
  "target": { "role": "tecnico", "zone": "norte", "user_id": "u-tec-07" },
  "severity": "high",
  "title": "EX-023 requiere intervención",
  "body": "Vibración 3.1σ sobre su baseline. Causa probable: desgaste de rodamiento.",
  "deep_link": "/incidents/INC-01JC8ZK"
}
```

- Atributos del mensaje Pub/Sub: `correlation_id`, `incident_id`, `event_type`.
- **Destino:** si `target.user_id` viene, `notify_bridge` lee `users/{user_id}.fcm_tokens[]`; si es `null`, envía a todos los `users` con `role == target.role` y `zone in [target.zone, "*"]`. Los tokens que FCM rechaza como no registrados se quitan del arreglo (`arrayRemove`).
- `title`/`body` ya vienen redactados por *notificar* según el `content_profile` de la regla (§10). `notify_bridge` no llama a la IA.

## 5. Firestore (tiempo real, chat, réplica y tokens push)

| Colección | Escribe | Lee | Para qué |
|---|---|---|---|
| `machines/{machine_id}` | Lambda replicar (Streams) | todos (según zona) | Mapa en vivo, mismo esquema que `Machine` |
| `incidents/{incident_id}` | Lambda replicar (solo ítems `META`; ignora `EVT#`) | todos (según rol) | Cola en vivo, mismo esquema que `Incident` |
| `incidents/{id}/messages/{msg_id}` | técnico, mantenimiento, supervisor | participantes | Chat del incidente. Campos: `author_id`, `role`, `text`, `quick_action?`, `attachment_path?`, `created_at`, `correlation_id` |
| `incidents/{id}/actions/{event_id}` | móvil del técnico | Cloud Function | Acciones (aceptar, resolver). La Cloud Function las reenvía a `POST /bridge/events` |
| `technicians/{tech_id}` | Lambda replicar | M S A (según zona) y el propio técnico | Ubicación y disponibilidad. `location.zone` **siempre** presente (= `technicians.zone`, #11) |
| `users/{uid}` | `api-lectura` (Admin SDK, en `POST /v1/auth/firebase-token`) | `notify_bridge` (Admin SDK); el propio usuario | Perfil para push: `user_id`, `role`, `zone`, `technician_id?`, `fcm_tokens[]`, `updated_at` |

- `uid` = `cognito:username` (`u-tec-07`).
- **Token FCM:** el front obtiene el token con `getToken()` (requiere service worker `firebase-messaging-sw.js`) y lo envía en el body de `POST /v1/auth/firebase-token` (`{ "fcm_token": "..." }`). `api-lectura` hace `arrayUnion` en `users/{uid}.fcm_tokens` y actualiza `role`/`zone`/`technician_id`. Los clientes no escriben `users/` directo (las Security Rules lo niegan); solo pueden leer su propio documento.
- Las Security Rules usan los claims `role`, `zone` y `technician_id` del custom token (§2.1).
- Tokens secretos (`ack_token`, `resolve_token`, `execution_arn`) nunca se replican.

## 6. Flujo de punta a punta con los contratos

1. Simulador → `POST /telemetry` (lote ≤100, cada 60 s) → SQS → Lambda procesar.
2. Anomalía → evento **AnomalyDetected** → Step Functions `GestionIncidente`.
3. Step Functions crea el incidente (`detected`), pide el diagnóstico a `ia-gemini` con `candidate_parts` (§8), deriva `required_specialty` (§8.2), calcula el técnico (`scoring`), lo asigna (`assigned`), notifica (§10: SNS email + Pub/Sub → FCM) y espera el `ack_token`.
4. Técnico acepta: web `POST /v1/incidents/{id}/ack`, o móvil escribe en Firestore → Cloud Function → `POST /bridge/events`. Ambos terminan en `SendTaskSuccess` → `in_progress`.
5. Chat en Firestore. Al terminar: `POST /v1/incidents/{id}/resolve` (segundo token) → `resolved` → resumen IA → registro en `maintenance-records` → `closed`.
6. Supervisor: `GET /v1/machines` e `/incidents`; mapa y chat en vivo por Firestore.

## 7. Ajustes a tener para el diagrama de arquitectura

1. **Flecha API Gateway → `ia-gemini`** para `POST /v1/assistant/chat`. Debe quedar **fuera de la VPC** (sale a Gemini y la VPC no tiene NAT).
2. **`api-comandos`** (antes `api-ack`): ack, assign, resolve, `technicians/me/status`, `ml/retrain` y `/bridge/events`. Fuera de la VPC (llama a Step Functions). `firebase-token` pasó a `api-lectura` (§2).
3. **Dos task tokens por incidente**: `ack_token` y `resolve_token`, guardados en el ítem META de DynamoDB.
4. **Quitar `WS /live`** de `requerimientos.md §5.5`. El tiempo real va por Firestore.

## 8. Invocaciones Lambda internas

### 8.1 `ia-gemini` (dueño A; la invocan la SFN `GestionIncidente`, `AnalisisDiario` y API Gateway)

Input: `{ "task", "correlation_id", "payload" }` · Output: `{ "result", "model": "gemini-2.5-flash" | "fallback", "degraded": bool, "prompt_version", "latency_ms" }`. Si Gemini falla o tarda más de 8 s, responde con `model: "fallback"`, `degraded: true`, `prompt_version: "<id>+fallback"` y un resultado determinista. **Nunca lanza error a la SFN por culpa de la IA.** Credencial: API key de AI Studio en Secrets Manager (`arquifusion/{stage}/gemini/api-key`, #22).

| `task` | `payload` | `result` |
|---|---|---|
| `diagnose` | `machine_id`, `machine_type`, `model`, `zone`, `severity`, `health_score`, `top_factors[]`, `latest_reading`, `recent_incidents[]`, **`candidate_parts[]`** | `probable_cause`, `suggested_action`, `confidence` (0-1), `parts_suggested[]` (`component_id`, **solo IDs presentes en `candidate_parts`**) |
| `summarize_by_role` | `incident` (schema `Incident`), `roles[]` | `{ "<rol>": { "title", "body" } }` |
| `common_cause` | `zone`, `incidents[]` (máquinas, factores, ventana) | `probable_common_cause`, `evidence[]`, `confidence` |
| `summarize_chat` | `incident_id`, `messages[]` (§5) | `summary`, `root_cause`, `actions_taken[]`, `parts_replaced[]` |
| `executive_report` | `figures` (KPIs de `AnalisisDiario`) | `summary_text`, `prompt_version` |
| `assistant_chat` | (vía API Gateway, body de `POST /v1/assistant/chat`) | respuesta de `POST /v1/assistant/chat` |

**`candidate_parts[]`** = `[{ "component_id", "name", "specialty" }]`. Lo arma la SFN (B): `GetItem catalog pk=MODEL#<model>` → `component_ids[]` → `BatchGetItem catalog pk=COMPONENT#<id>` → `{component_id, name, specialty}`. Para `CAT-336` son 21 componentes (incluye `CMP-014`). Fixtures: `fixtures/ia/diagnose_request.json` / `diagnose_response.json`.

### 8.2 Regla de `required_specialty` (#18)

La SFN la calcula **después** de `diagnose` y antes de `scoring`:

1. Si `parts_suggested` no está vacío → `required_specialty` = `specialty` (de `candidate_parts`) del **primer** `component_id` de `parts_suggested`.
2. Si está vacío (o el diagnóstico vino `degraded` sin repuestos) → se usa la variable del `top_factors[0]` (la de mayor |z|) con esta tabla:

| Variable dominante | `required_specialty` |
|---|---|
| `temperature_c` | `motor` |
| `vibration_mm_s` | `motor` |
| `fuel_rate_lph` | `motor` |
| `rpm` | `motor` |
| `pressure_bar` | `hidraulica` |
| `load_pct` | `hidraulica` |
| `speed_kmh` | `neumaticos` |
| (incidente por `MachineSilent`) | `electrica` |
| cualquier otra / sin factores | `motor` |

Los valores son el enum `specialty` del OpenAPI (= `technicians.specialties[]` y `catalog.specialty` del seed).

### 8.3 `scoring` (dueño B) — fixtures `internal/scoring_*.json`

Request: `{ incident_id, correlation_id, machine_id, zone, severity, location{lat, lon, zone}, required_specialty, exclude_technician_ids[] }` (`location` = ubicación actual de la máquina en `machines`).

Response (**un único shape**, el mismo que `Candidate` en `frontend/src/lib/scoring.ts`):

```json
{ "selected": "TEC-07",
  "weights": { "specialty": 0.35, "eta": 0.35, "availability": 0.15, "load": 0.15 },
  "candidates": [ { "technician_id": "TEC-07", "name": "Pedro Rojas", "score": 0.98, "eta_min": 3,
                    "breakdown": { "specialty": 1, "eta": 0.93, "availability": 1, "load": 1 } } ] }
```

- Candidatos = técnicos de la `zone` del incidente que no estén en `exclude_technician_ids`, ordenados por `score` desc y luego `eta_min` asc. `selected` = `null` si no hay candidatos (la SFN escala).
- `breakdown` en [0, 1]: `specialty` = 1 si tiene la especialidad (0.5 si no hay `required_specialty`), `eta` = max(0, 1 − eta_min/45), `availability` = 1/0, `load` = max(0, 1 − current_load/3). `eta_min` = haversine a 25 km/h + 2 min (`frontend/src/lib/geo.ts`).
- `weights` por severidad: critical 0.30/0.45/0.15/0.10 · high 0.35/0.35/0.15/0.15 · medium 0.40/0.25/0.15/0.20 · low e info 0.40/0.20/0.15/0.25 (specialty/eta/availability/load). `score` = Σ peso × breakdown, redondeado a 2 decimales.
- TRZ-03: la SFN guarda `candidates` completo en el ítem META (`scoring_candidates`) y `technician_score` = score del elegido.
- Con el seed v2, para EX-023 (high, motor) gana **TEC-07** (0.98) y el segundo es **TEC-01** (0.95), útil para mostrar rechazo → reasignación.

### 8.4 `correlacion` (dueño B) — fixtures `internal/correlacion_*.json`

Request `{ incident_id, zone, reading_ts }` · Response `{ parent_incident_id | null, machines[] }`. Consulta `anomalies` por GSI `by_zone` (`zone` = Z, `detected_at` entre `reading_ts − 15 min` y `reading_ts`).

## 9. Recursos compartidos AWS: convención de nombres

Todos los workers referencian los recursos de `infra/base` **por nombre** (no por `terraform_remote_state`). B los crea; `{p}` = `arquifusion-{stage}`.

| Recurso | Nombre | Uso |
|---|---|---|
| Tablas DynamoDB | `{p}-machines`, `{p}-machine-state`, `{p}-idempotency`, `{p}-anomalies`, `{p}-incidents`, `{p}-technicians`, `{p}-inventory`, `{p}-catalog`, `{p}-warehouses`, `{p}-notification-rules`, `{p}-audit-events`, `{p}-maintenance-records`, `{p}-insights` | Ver `dynamodb.md` (claves y GSIs) |
| Bus EventBridge | `{p}-fleet-events` | `AnomalyDetected`, `MachineSilent`, `IncidentStateChanged` |
| API REST | `{p}-api`, stage `v1` | A agrega `POST /telemetry` (API key); B cablea `/v1/*` (Cognito) y `POST /v1/assistant/chat` → `ia-gemini` |
| SNS | `{p}-alerts-{rol}` (6 roles, email) · **`{p}-platform-alarms`** (alarmas de DLQ, errores y throttling de Lambdas; suscripción email del equipo) | notificar (B) · CloudWatch Alarms (A, B) |
| Secretos | `arquifusion/{stage}/gemini/api-key` (A) · `arquifusion/{stage}/gcp/service-account` (replicar, notificar → Pub/Sub, firebase-token) · `arquifusion/{stage}/bridge-gcp` (API key de `/bridge/*`) | |
| Rol | `LabRole` | Todo |

**Lo que A publica en SSM** (para que B y C no dependan del state de A):

| Parámetro | Valor |
|---|---|
| `/arquifusion/{stage}/lambda/ia-gemini/arn` | ARN de `ia-gemini` (B lo usa en la SFN y en la ruta del asistente) |
| `/arquifusion/{stage}/sfn/reentrenamiento/arn` | ARN de la SFN (B lo usa en `POST /v1/ml/retrain`) |
| `/arquifusion/{stage}/model/active_version` | Versión activa del modelo |
| `/arquifusion/{stage}/thresholds/{model}` | Umbrales de la capa 1 por modelo (JSON), derivados de `MODEL#<model>.nominal` (#2) |

**Tras `terraform apply` de `infra/ingest`**, quien despliegue crea un nuevo deployment del stage `v1` de `{p}-api` para publicar `POST /telemetry`.

### 9.1 Key schema (todas las claves `pk`/`sk` de tipo string)

| Tabla | `pk` | `sk` | GSI | Escribe |
|---|---|---|---|---|
| `{p}-machines` | `operation_id#machine_id` (`OP-01#EX-023`) | `META` | `by_zone`: `zone` → `machine_id` | C (seed), A (telemetría), B (`open_incident_id`) |
| `{p}-machine-state` | `machine_id` o `COHORT#type#zone` | `LAST`, `BASELINE`, `AGG#1h#YYYY-MM-DDTHH` | — | A |
| `{p}-idempotency` | `machine_id#timestamp` · `NTF#…` (throttle de notificar) | — | — | A, B. TTL `expires_at` |
| `{p}-anomalies` | `machine_id` | `<detected_at>#<anomaly_id>` | **`by_zone`: `zone` → `detected_at`** | A |
| `{p}-incidents` | `INC#<incident_id>` | `META` · `EVT#<ts>#<event_id>` | `by_machine`: `machine_id` → `detected_at` · `by_status`: `status` → `detected_at` | B |
| `{p}-technicians` | `TECH#<technician_id>` | `META` | `by_zone`: `zone` → `technician_id` | C (seed), B |
| `{p}-catalog` | `COMPONENT#<id>` · `MODEL#<model_id>` | `META` | — | C (seed) |
| `{p}-inventory` | `location_id` (`WH-01`) | `component_id` (`CMP-014`) | `by_component`: `component_id` → `warehouse_id` | C (seed), B, A |
| `{p}-warehouses` | `warehouse_id` (`WH-04`) | `META` | — | C (seed) |
| `{p}-notification-rules` | `EVENT#<event_type>` | `ROLE#<role>` | — | C (seed) |
| `{p}-audit-events` | `<entidad>#<id>` | `<ts>#<event_id>` | — | B (append-only) |
| `{p}-maintenance-records` | `machine_id` (`EX-023`) | `<performed_at>#<record_id>` | — | B (correctivo al cerrar), A (lee) |
| `{p}-insights` | `kind` (`maintenance_plan`, `kpis#7d`, …) | `LATEST` · `YYYY-MM-DD` (+ `#<zone>` en `kpis#*`) | — | A |

**Anomalías (#7):** el GSI de `anomalies` es **`by_zone` (hash `zone`, range `detected_at`)**. `detected_at` = `timestamp` de la lectura que disparó la anomalía (ISO 8601 UTC, el mismo valor que `reading_ts` del evento). `procesar` **debe** escribir `zone` y `detected_at` en cada ítem (el GSI es disperso). Ya **no existen** `gsi1pk`/`gsi1sk`. Atributos: `anomaly_id`, `machine_id`, `zone`, `detected_at`, `severity`, `anomaly_score`, `top_factors[]`, `health_score`, `model_version`, `correlation_id`.

**Incidentes (#26):**
- Ítem `META`: `incident_id`, **`machine_id`** (escalar = máquina principal; lo indexa `by_machine`), **`machine_ids[]`** (principal primero + hijas correlacionadas; lo expone el OpenAPI), `zone`, `severity`, `status`, `detected_at`, `assigned_technician_id`, `technician_score`, `scoring_candidates[]`, `escalated`, `ai_diagnosis`, `required_specialty`, `parent_incident_id`, `child_incident_ids[]`, `assigned_at`, `accepted_at`, `resolved_at`, `downtime_minutes`, `components_replaced[]`, `cost_usd`, `resolution_summary`, `correlation_id`, `source` (`anomaly` | `silence`). Secretos (nunca salen): `ack_token`, `resolve_token`, `execution_arn`.
- Ítems `EVT#<ts>#<event_id>` (historial): `entity = "incident_event"`, `event_type`, `from`, `to`, `actor{}`, `occurred_at`, `correlation_id`. **No** llevan `incident_id`, `status`, `machine_id` ni `detected_at` a nivel raíz (así no entran a los GSIs ni los cuenta dos veces el `Scan` de `kpis_report`). `replicar` los ignora (`sk != META`).

**Mantenimiento (`{p}-maintenance-records`, #3):** ítem = `record_id` (`MR-<ULID>`), `machine_id`, `zone`, `type` (`preventive` | `corrective`), `performed_at` (ISO 8601), `technician_id`, `incident_id?`, `operating_hours`, `components[]` = `[{ "component_id", "quantity" }]`, `cost_usd`, `notes?`. La SFN escribe uno `corrective` al cerrar el incidente (con `components_replaced` y `cost_usd` del `ResolveRequest`). A lo lee con `Scan` (`analytics_common/records.py`); C lo consulta por máquina (`Query pk = machine_id`) para el timeline.

**Insights (`{p}-insights`, #3/#26):** `pk` = `kind` (lista en `services/ml/arquifusion_ml/insights.py`), `sk` = `LATEST` (lo que lee C) o `YYYY-MM-DD` (histórico). `data` es **exactamente** el `data` de la respuesta del endpoint en `openapi.yaml`; para arreglos, C filtra por `zone` sobre cada fila. Atributos extra: `generated_at`, `correlation_id`. Como `kpis#7d`/`kpis#30d` son un objeto (no se puede filtrar por fila), A escribe **además** un ítem por zona: `sk = LATEST#<zone>` (y `YYYY-MM-DD#<zone>`); `sk = LATEST` sigue siendo el agregado de toda la flota (`ALL`). `GET /v1/analytics/kpis?zone=norte` lee `LATEST#norte`.

**Almacenes (`{p}-warehouses`, #19):** ítem = `warehouse_id`, `name`, `zone`, `location{lat, lon, zone}`. 4 almacenes, uno por zona (WH-04 = oeste). La SFN lo usa para la rama stock (distancia almacén → máquina) y A para el pronóstico por zona. `inventory` mantiene `zone` y `warehouse_name` redundantes.

**Modelos de máquina (`catalog` `MODEL#<model_id>`, #13).** Atributos que A debe leer en vez de constantes propias: `model_id`, `brand`, `type`, `payload_t` (t por ciclo; 0 en bulldozer/perforadora), `maintenance_interval_h` (horas de operación entre mantenimientos preventivos: 250, o 500 en camiones), `nominal{variable: [media, desv]}` (base del simulador y de los umbrales por modelo), `component_ids[]`. El seed calcula `next_maintenance_at` con 16 h de uso diario.

**Dedup de `AnomalyDetected` sobre `{p}-machines`** (regla de costo §3). `procesar` emite solo si se cumple de forma condicional `attribute_exists(pk) AND attribute_not_exists(open_incident_id) AND (attribute_not_exists(anomaly_lock_until) OR anomaly_lock_until < :now)`, y en la misma escritura fija `anomaly_lock_until = now + 10 min`. La SFN de B fija `open_incident_id` al crear el incidente y lo elimina al cerrarlo.

**`operation_id`**: `TelemetryReading` no lo trae. `procesar` lo toma de `DEFAULT_OPERATION_ID` (`OP-01`) mientras haya una sola operación.

**Propiedad de `machines`.** `model`, `type`, `zone`, `home_location` y `expected_interval_s` son del seed (C) y **nadie los sobrescribe** (#1). `procesar` escribe solo `status`, `severity`, `health_score`, `last_seen_at`, `top_factors`, `model_version`, `location`, `operating_hours` (con `attribute_exists(pk)`: un ID desconocido no crea máquinas). La SFN de B **no** escribe `status`: el estado del incidente se refleja en `open_incident_id` y en el ítem del incidente.

**Atributos que lee la analítica de A** (`AnalisisDiario`):

| Tabla | Atributos |
|---|---|
| `{p}-incidents` (solo `sk = META`) | `incident_id`, `machine_id`, `zone`, `status`, `severity`, `detected_at`, `resolved_at`, `downtime_minutes` |
| `{p}-maintenance-records` | `machine_id`, `performed_at`, `type`, `components[]`, `cost_usd`, `operating_hours` |
| `{p}-inventory` | `location_id` (`pk`), `component_id` (`sk`), `stock`, `stock_min`, `stock_max`, `zone` |
| `{p}-catalog` | `component_id`, `name`, `specialty`, `compatible_models[]`, `cost_usd`, `lead_time_days` · `MODEL#…` (arriba) |
| `{p}-warehouses` | `warehouse_id`, `zone`, `location` |

`preventivo` escribe `next_maintenance_at` en `{p}-machines`, y las filas de `maintenance_plan`, `fuel#*` y `productivity#*` llevan `zone` para que `api-lectura` filtre.

## 10. Notificaciones: transición → `event_type` (#14)

`notificar` (B) recibe de la SFN `{ event_type, incident_id?, machine_id, zone, severity, technician_id?, correlation_id }`, hace `Query notification-rules pk = EVENT#<event_type>`, filtra `enabled` y `severity ≥ severity_min`, y por cada regla envía por sus `channels`. La SFN emite además `IncidentStateChanged` con el mismo `event_type` (§3).

| Disparador | `status` from → to | `event_type` |
|---|---|---|
| SFN crea el incidente desde `AnomalyDetected` | — → `detected` | `incident.detected` |
| SFN crea el incidente desde `MachineSilent` | — → `detected` | `machine.silent` |
| `scoring` elige técnico, `assign` manual o `reject` → siguiente candidato | `detected`/`assigned` → `assigned` | `incident.assigned` |
| `ack` con `accept` | `assigned` → `in_progress` | `incident.in_progress` |
| `resolve` | `in_progress` → `resolved` | `incident.resolved` |
| Resumen IA guardado, cierre | `resolved` → `closed` | `incident.closed` |
| Vence el `ack_token` (timeout) o no hay candidatos | sin cambio (`escalated = true`) | `incident.escalated` |
| Rama stock sin repuesto en la zona, o el descuento al cierre deja `stock < stock_min` | — | `parts.shortage` |
| `AnalisisDiario` escribe `report#daily` | — | `report.daily` |

**Canales:**
- `push` → Pub/Sub `notificaciones` (§4). Para el rol `tecnico` en eventos `incident.*`, el destino es **solo** el técnico asignado (o el nuevo candidato en `incident.escalated`): `target.user_id = technicians.user_id`. Para los demás roles, `target.user_id = null` y `target.zone = zone` del incidente.
- `email` → SNS `{p}-alerts-{rol}`.
- `dashboard` → no se envía nada: el cambio ya llega al front por la réplica a Firestore.
- Throttle: `notificar` hace `PutItem` condicional en `{p}-idempotency` con `pk = NTF#<event_type>#<role>#<incident_id|machine_id>` y `expires_at = now + throttle_minutes`; si existe, no envía.

Las reglas sembradas (`fixtures/seed/notification_rules.json`, seed v2) cubren exactamente los `event_type` de esta tabla.
