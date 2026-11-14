# api_comandos

- **Dueño:** Persona B
- **Qué hace:** Comandos REST: ack, assign, resolve, technicians/me/status, ml/retrain, bridge/events → SendTaskSuccess. (Antes `api-ack`.)
- **Consume:** API Gateway `/v1/*` (JWT) y `/bridge/events` (API key)
- **Produce:** `Incidents`, `SendTaskSuccess`, `StartExecution`
- **Cubre:** RF-06.4, RF-11.1, RF-16.5
- **Despliegue:** Fuera de la VPC.
- **Cómo probar:** `pytest services/incidents/api_comandos/tests`
