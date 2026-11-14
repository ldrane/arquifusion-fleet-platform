# api_comandos

- **Dueño:** Persona B
- **Qué hace:** Comandos REST: ack, assign, resolve, technicians/me/status, ml/retrain, bridge/events → SendTaskSuccess. (Antes `api-ack`.)
- **Consume:** API Gateway (stage `v1`, rutas sin prefijo): `/incidents/{incident_id}/{ack,assign,resolve}`, `/technicians/me/status`, `/ml/retrain` (JWT) y `/bridge/events` (API key, idempotente por `event_id` con `BRG#…` en idempotency).
- **Reglas:** el técnico solo actúa sobre incidentes asignados a él (`custom:technician_id`; por el puente se valida `technicians.user_id`), otros roles validan zona; output a la SFN con `actor {type, user_id, role, technician_id}`; respuesta = recurso completo + `meta.pending_transition`. Env: `TABLE_INCIDENTS`, `TABLE_TECHNICIANS`, `TABLE_IDEMPOTENCY`, `CORS_ORIGIN`, `RETRAIN_STATE_MACHINE_ARN`.
- **Produce:** `Incidents`, `SendTaskSuccess`, `StartExecution`
- **Cubre:** RF-06.4, RF-11.1, RF-16.5
- **Despliegue:** Fuera de la VPC.
- **Cómo probar:** `pytest services/incidents/api_comandos/tests`
