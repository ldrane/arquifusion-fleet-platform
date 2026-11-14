# auditoria

- **Dueño:** Persona B
- **Qué hace:** consume los eventos de dominio del bus (regla `{p}-audit`, contratos.md §3) y escribe `audit-events` (append-only, `pk = incident#<id>` o `machine#<id>`, `sk = <occurred_at>#<event_id>`) y el historial `EVT#<occurred_at>#<event_id>` del incidente (§9.1: sin `incident_id`/`status`/`machine_id`/`detected_at` en la raíz). Idempotente.
- **Consume:** `IncidentStateChanged`, `AnomalyDetected`, `MachineSilent` (EventBridge). No usa Streams: el evento ya trae `actor` y `event_type`.
- **Produce:** `audit-events`, ítems `EVT#` en `incidents`
- **Cubre:** RNF-15, TRZ-02
- **Despliegue:** Dentro de la VPC si H0 lo permite.
- **Cómo probar:** `pytest services/incidents/auditoria/tests`
