# notify_bridge (Cloud Function Gen2)

- **Dueño:** Persona B
- **Qué hace:** (a) Pub/Sub `notificaciones` → push FCM; (b) trigger Firestore `incidents/{id}/actions/{event_id}` → `POST /bridge/events` en AWS (API key `bridge-gcp`).
- **Consume:** mensaje Pub/Sub (`contracts/fixtures/pubsub/notificacion.json`), documentos `actions`.
- **Produce:** push FCM, llamada a `/bridge/events`.
- **Cubre:** RF-10.2, RF-16.5, MH-MC-02.
- **Infra:** `infra/gcp/notify.tf` (topic `notificaciones`, funciones `{p}-notify-push` y `{p}-notify-actions`, secreto `bridge-api-key` = JSON `{api_key, url}` copiado de AWS `arquifusion/<stage>/bridge-gcp`, SA `notify-bridge`).
- **Detalle:** push a `users/{uid}.fcm_tokens` (por `user_id`, o por `role` y `zone in [zone, "*"]`), `arrayRemove` de tokens no registrados. Acciones: valida que `actor.role` coincida con `users/{uid}.role`, agrega `technician_id`/`zone` del perfil, reintenta en 5xx y marca `bridge_status` en el documento.
- **Cómo probar:** `pytest gcp/functions/notify_bridge/tests`
