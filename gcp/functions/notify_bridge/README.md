# notify_bridge (Cloud Function Gen2)

- **Dueño:** Persona B
- **Qué hace:** (a) Pub/Sub `notificaciones` → push FCM; (b) trigger Firestore `incidents/{id}/actions/{event_id}` → `POST /bridge/events` en AWS (API key `bridge-gcp`).
- **Consume:** mensaje Pub/Sub (`contracts/fixtures/pubsub/notificacion.json`), documentos `actions`.
- **Produce:** push FCM, llamada a `/bridge/events`.
- **Cubre:** RF-10.2, RF-16.5, MH-MC-02.
- **Cómo probar:** `pytest gcp/functions/notify_bridge/tests`
