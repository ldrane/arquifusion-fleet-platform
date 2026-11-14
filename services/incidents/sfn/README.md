# Step Function `GestionIncidente` (Standard, JSONata)

- **Dueño:** Persona B
- **Disparo:** reglas EventBridge `{p}-anomaly` (`AnomalyDetected`, severidad medium+) y `{p}-silent` (`MachineSilent`) en `{p}-fleet-events`.
- **Flujo:** ver `infra/incidents/README.md`. Dedup con `open_incident_id` → `CrearIncidente` → Parallel (diagnóstico IA con `candidate_parts` ‖ correlación) → `required_specialty` → scoring → asignar → `EsperarAceptacion` (`ack_token`, timeout + escalamiento) → `EsperarResolucion` (`resolve_token`) → resumen IA → `corrective` → `closed`.
- **Emite:** `IncidentStateChanged` (`from`, `to`, `event_type` §10, `actor`) en cada transición; `auditoria` escribe el historial `EVT#` y `notificar` notifica.
- **Placeholders** (`templatefile` en `infra/incidents/main.tf`): `operation_id`, `table_*`, `event_bus_name`, `fn_*`, timeouts y `max_escalations`.
- **Cubre:** RF-06, RF-10, RF-11, RF-12, MH-SFN-01.
- **Cómo probar:** `pytest services/incidents/sfn/tests` (validación estructural; las expresiones JSONata se validan al `terraform apply`).
