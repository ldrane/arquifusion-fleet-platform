# Contratos de integración — ArquiFusion Fleet Platform

> Grupo 27 · RootAccess. Fuente de verdad técnica: `openapi.yaml` (REST). Este documento resume el resto: eventos, Firestore y Pub/Sub.
> Regla de trabajo: **si cambia un contrato, se cambia aquí primero** y recién después el código.

## 1. Convenciones (valen para todo)

| Tema | Regla |
|---|---|
| Formato | JSON `snake_case`. Fechas ISO 8601 UTC. Unidades en el nombre del campo (`temperature_c`, `fuel_rate_lph`). |
| IDs | Máquina `EX-023` (2 letras + número) · Técnico `TEC-07` · Incidente `INC-<ULID>` · Almacén `WH-01` · Componente `CMP-014`. |
| Enums | `severity`: info, low, medium, high, critical · `machine.status`: operational, stopped, maintenance, needs_intervention, silent · `incident.status`: detected, assigned, in_progress, resolved, closed. |
| Respuesta OK | `{ "data": ..., "meta": {...} }` |
| Respuesta error | `{ "error": { "code", "message", "details": [] }, "correlation_id" }` |
| Paginación | `?limit=` (1-100) y `?cursor=`; siguiente página en `meta.next_cursor`. |
| Trazabilidad | `X-Correlation-Id` en la request (se genera si falta). Viaja en eventos, Pub/Sub, Firestore y logs. |
| Versionado | Prefijo `/v1`. Los eventos llevan `version: 1`. |

**Códigos de error**

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `VALIDATION_ERROR` | JSON Schema inválido |
| 401 | `UNAUTHENTICATED` | Falta JWT o API key, o no es válida |
| 403 | `FORBIDDEN` | El grupo de Cognito no tiene permiso |
| 404 | `NOT_FOUND` | No existe el recurso |
| 409 | `INCIDENT_STATE_INVALID` / `DUPLICATE_EVENT` | Ack sobre un incidente ya aceptado, o evento repetido |
| 429 | `RATE_LIMITED` | Usage plan agotado |
| 503 | `UPSTREAM_UNAVAILABLE` | Falla GCP/Gemini sin respuesta de respaldo |
| 500 | `INTERNAL` | Error no controlado |

## 2. Endpoints (26 operaciones, 3 familias)

Autenticación: **K** = API key · **J** = JWT Cognito. Roles: **O**perador, **T**écnico, **M**antenimiento, **S**upervisor, **A**dmin, **G**erencia.

| Método y ruta | Auth | Roles | Lambda | Cubre |
|---|---|---|---|---|
| `POST /telemetry` | K | simulador | — (APIGW → SQS) | RF-01 |
| `GET /v1/me` | J | todos | api-lectura | RNF-08 |
| `POST /v1/auth/firebase-token` | J | todos | api-ack | RF-16, MH-SEC-07 |
| `GET /v1/machines` | J | todos | api-lectura | RF-05 |
| `GET /v1/machines/{id}` | J | todos | api-lectura | RF-02, RNF-13 |
| `GET /v1/machines/{id}/telemetry` | J | T M S A G | api-lectura | RF-02.3 |
| `GET /v1/machines/{id}/timeline` | J | T M S A G | api-lectura | RF-11.4 |
| `GET /v1/incidents` | J | todos | api-lectura | RF-11 |
| `GET /v1/incidents/{id}` | J | todos | api-lectura | RF-11, RF-12 |
| `POST /v1/incidents/{id}/ack` | J | T M | api-ack | RF-06.4, RF-10.4 |
| `POST /v1/incidents/{id}/assign` | J | M S A | api-ack | RF-06.4 |
| `POST /v1/incidents/{id}/resolve` | J | T M | api-ack | RF-11.1 |
| `GET /v1/technicians` | J | M S A | api-lectura | RF-05.3, RF-06.1 |
| `PUT /v1/technicians/me/status` | J | T | api-ack | RF-06.1 |
| `GET /v1/inventory` | J | M S A | api-lectura | RF-04.2, RF-04.6 |
| `GET /v1/parts/ranking` | J | M S A | api-lectura | RF-04.3 |
| `GET /v1/parts/forecast` | J | M A | api-lectura | RF-04.4 |
| `GET /v1/maintenance/plan` | J | M S A | api-lectura | RF-03 |
| `GET /v1/analytics/fuel` | J | S A G | api-lectura | RF-07 |
| `GET /v1/analytics/productivity` | J | S A G | api-lectura | RF-08 |
| `GET /v1/analytics/kpis` | J | S A G | api-lectura | RF-11.4 |
| `GET /v1/reports/latest` | J | A G S | api-lectura | RF-10.3, RF-13.3 |
| `GET /v1/ml/model` | J | A M | api-lectura | MH-AI-04 |
| `POST /v1/ml/retrain` | J | A | api-ack | RF-13.2 |
| `POST /v1/assistant/chat` | J | T M S A G | ia-gemini | RF-14 |
| `POST /bridge/events` | K | GCP | api-ack | RF-16, MH-MC-02 |

Lo que **no** es endpoint, a propósito: chat del incidente, mapa en tiempo real y adjuntos (van por Firestore y Cloud Storage con el SDK), asignación automática y notificaciones (las hace Step Functions).

## 3. Eventos (EventBridge, bus `fleet-events`)

Envoltorio común (`detail`): `{ "event_id", "correlation_id", "occurred_at", "version": 1, "data": {...} }`

| `source` → `detail-type` | Lo emite | Lo consume | `data` |
|---|---|---|---|
| `arquifusion.processor` → **AnomalyDetected** | Lambda procesar | Regla → Step Functions `GestionIncidente` | `machine_id`, `zone`, `severity`, `anomaly_score`, `top_factors[]`, `health_score`, `model_version`, `reading_ts` |
| `arquifusion.heartbeat` → **MachineSilent** | Lambda heartbeat | Regla → `GestionIncidente` (severidad baja) | `machine_id`, `last_seen_at`, `expected_interval_s` |
| `arquifusion.incident` → **IncidentStateChanged** | Step Functions | Lambda notificar / auditoría | `incident_id`, `from`, `to`, `actor`, `technician_id?` |

Regla de costo: `AnomalyDetected` se emite **solo si no hay un incidente abierto para esa máquina** (escritura condicional en DynamoDB). Así no se lanza una ejecución por cada lectura.

## 4. Mensaje Pub/Sub (AWS → GCP, topic `notificaciones`)

Lo publica la Lambda *notificar* por REST; la Cloud Function lo convierte en push FCM.

```json
{
  "notification_id": "ntf-01JC8Z",
  "correlation_id": "7c1e4b1a-0d2f-4a55-9c50-3b3f0a6f1e11",
  "incident_id": "INC-01JC8ZK",
  "target": { "role": "tecnico", "user_id": "u-tec-07" },
  "severity": "high",
  "title": "EX-023 requiere intervención",
  "body": "Vibración 3.1σ sobre su baseline. Causa probable: desgaste de rodamiento."
}
```
Los atributos `correlation_id` e `incident_id` también van como *attributes* del mensaje.

## 5. Firestore (tiempo real, chat y réplica)

| Colección | Escribe | Lee | Para qué |
|---|---|---|---|
| `machines/{machine_id}` | Lambda replicar (Streams) | todos (según zona) | Mapa en vivo, mismo esquema que `Machine` |
| `incidents/{incident_id}` | Lambda replicar | todos (según rol) | Cola en vivo, mismo esquema que `Incident` |
| `incidents/{id}/messages/{msg_id}` | técnico, mantenimiento, supervisor | participantes | Chat del incidente. Campos: `author_id`, `role`, `text`, `quick_action?`, `attachment_path?`, `created_at`, `correlation_id` |
| `incidents/{id}/actions/{event_id}` | móvil del técnico | Cloud Function | Acciones (aceptar, resolver). La Cloud Function las reenvía a `POST /bridge/events` |
| `technicians/{tech_id}` | Lambda replicar | M S A | Ubicación y disponibilidad |

Las Security Rules usan los claims `role` y `zone` del custom token (`POST /v1/auth/firebase-token`).

## 6. Flujo de punta a punta con los contratos

1. Simulador → `POST /telemetry` (lote ≤100) → SQS → Lambda procesar.
2. Anomalía → evento **AnomalyDetected** → Step Functions `GestionIncidente`.
3. Step Functions crea el incidente, calcula el técnico, notifica (SNS email + Pub/Sub → FCM) y espera el `ack_token`.
4. Técnico acepta: web `POST /v1/incidents/{id}/ack`, o móvil escribe en Firestore → Cloud Function → `POST /bridge/events`. Ambos terminan en `SendTaskSuccess`.
5. Chat en Firestore. Al terminar: `POST /v1/incidents/{id}/resolve` (segundo token) → resumen IA → `closed`.
6. Supervisor: `GET /v1/machines` e `/incidents`; mapa y chat en vivo por Firestore.

## 7. Ajustes a tener para el diagrama de arquitectura

El diagrama es coherente con el contrato. Faltan estos 4 detalles para que coincida 1 a 1:

1. **Flecha API Gateway → `ia-gemini`** para `POST /v1/assistant/chat`. Hoy `ia-gemini` solo cuelga de Step Functions. Debe quedar **fuera de la VPC**, porque necesita salir a Vertex AI y la VPC no tiene NAT.
2. **`api-ack` pasa a ser la Lambda de comandos**: ack, assign, resolve, `technicians/me/status`, `ml/retrain` y `firebase-token`. Debe estar **fuera de la VPC** (lee Secrets Manager y llama a Step Functions). Conviene renombrarla `api-comandos`. Si no, el nombre del diagrama y el de este contrato deben coincidir.
3. **Dos task tokens por incidente**: `ack_token` y `resolve_token`, guardados en el ítem de DynamoDB. El flujo espera dos callbacks, no uno.
4. **Quitar `WS /live`** de `requerimientos.md §5.5`. El diagrama ya usa Firestore para el tiempo real.
