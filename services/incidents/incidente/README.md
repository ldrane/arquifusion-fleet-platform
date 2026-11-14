# incidente

- **Dueño:** Persona B
- **Qué hace:** pasos de dominio de la SFN `GestionIncidente` que escriben estructuras anidadas: `contexto` (payload de `diagnose` con `candidate_parts`), `enriquecer` (`ai_diagnosis`, `required_specialty` §8.2, `parent_incident_id`/`machine_ids`, rama stock), `asignar` (`scoring_candidates`, `technician_score`, `current_load`), `guardar_token` (`ack_token`/`resolve_token` para `.waitForTaskToken`), `resolver` (downtime), `cerrar` (registro `corrective`, descuento de inventario, libera `open_incident_id`) y `liberar`.
- **Consume:** invocación desde la SFN `{ "action": ..., "incident_id": ... }`.
- **Produce:** `incidents` (META), `maintenance-records`, `inventory`, `technicians.current_load`, `machines.open_incident_id`.
- **Cubre:** RF-06, RF-11.1, RF-11.2, RF-04.6, TRZ-03.
- **Cómo probar:** `pytest services/incidents/incidente/tests` (moto).
