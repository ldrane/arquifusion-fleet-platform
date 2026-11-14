# notify_push

- **Dueño:** Persona B
- **Qué hace:** Push FCM desde AWS cuando el proyecto GCP **no tiene facturación** (`infra/gcp` con `gcp_billing = false`). Reemplaza a la Cloud Function `notify-push` con la **misma lógica** (`handle_notification` de `gcp/functions/notify_bridge/main.py`, copiado en el zip como `notify_bridge.py`).
- **Consume:**
  - Suscripción push de Pub/Sub `notificaciones-push` → `POST /bridge/push` (sin authorizer de API Gateway). Valida el token OIDC de Google: `aud = arquifusion-notify-push`, `email = pubsub-push@<project>.iam.gserviceaccount.com`.
  - Invocación directa `{"notification": {...}, "attributes": {...}}` desde `notificar` cuando `PUSH_MODE=direct` (plan B si no se puede crear la suscripción push).
- **Produce:** push FCM HTTP v1 a `users/{uid}.fcm_tokens[]`; quita los tokens no registrados (`removeAllFromArray`).
- **GCP por REST, sin SDK:** Firestore (`get`, `runQuery`, `commit`) y FCM con la SA `aws-integration` (`datastore.user` + `firebasecloudmessaging.admin`), token OAuth2 firmado con stdlib (`gcp_auth.py`).
- **Cubre:** RF-10.2, MH-MC-02.
- **Cómo probar:** `pytest services/incidents/notify_push/tests`
