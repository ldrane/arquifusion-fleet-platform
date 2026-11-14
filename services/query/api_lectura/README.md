# api_lectura

- **Dueño:** Persona C
- **Qué hace:** todos los GET con `x-lambda: api-lectura` de `contracts/openapi.yaml` y `POST /auth/firebase-token`. RBAC por rol (`x-roles`) y zona (`custom:zone`), paginación por cursor en `/machines` e `/incidents`.
- **Rutas:** sin prefijo `/v1` (el stage de API Gateway ya es `v1`: URL final `…/v1/me`). Enruta por `(httpMethod, resource)`; los parámetros de ruta se llaman `{machine_id}` e `{incident_id}` como en el OpenAPI.
- **Consume:** tablas `TABLE_MACHINES`, `TABLE_MACHINE_STATE`, `TABLE_ANOMALIES`, `TABLE_INCIDENTS`, `TABLE_TECHNICIANS`, `TABLE_INVENTORY`, `TABLE_WAREHOUSES`, `TABLE_MAINTENANCE_RECORDS`, `TABLE_INSIGHTS` (contratos.md §1.1) y el secreto `FIREBASE_SECRET_NAME` (`arquifusion/{stage}/gcp/service-account`).
- **Produce:** respuestas del OpenAPI (`{data, meta}`), custom token de Firebase con claims `role`, `zone`, `technician_id` y `users/{uid}.fcm_tokens[]` en Firestore (arrayUnion).
- **Cubre:** RF-02.3, RF-03, RF-04, RF-05, RF-06.1, RF-07, RF-08, RF-11, RF-13, RF-16, RNF-08.
- **Despliegue:** `infra/query`. **Fuera de la VPC**: `firebase-token` necesita Secrets Manager y Firestore (Internet).
- **Cómo probar:** `python -m pytest services/query -q` (moto con los seeds reales; Firebase con fakes).

## Decisiones

| Tema | Decisión |
|---|---|
| Orden y paginación | `/incidents`: abiertos primero, severidad desc, abiertos del más antiguo al más nuevo y cerrados al revés (igual que el demo del front). Se lee la lista completa (tope 5000) y se pagina por offset, así el orden es estable entre páginas. |
| Zona | La de `custom:zone` manda. Pedir otra zona por `?zone=` = 403; leer un recurso de otra zona = 404. |
| Telemetría | `procesar` (A) solo guarda agregados de 1 h (`AGG#1h#…`). Con `resolution=1m` se devuelven buckets de 1 h y `meta.resolution = "1h"`. `health_score` sale de `vars.health_score.avg` si A lo escribe; si no, `null`. |
| Insights | Listas sin datos todavía → `[]` con `meta.generated_at = null`. Objetos (`kpis`, `reports/latest`, `ml/model`) sin datos → 404 `NOT_FOUND`. `kpis` con zona lee `sk = LATEST#<zone>`. |
| Firebase | Custom token firmado localmente con `google-auth` (sin `firebase-admin`). Si registrar el `fcm_token` falla, igual se devuelve el token (`meta.fcm_registered = false`): el push no tumba el tiempo real. |
