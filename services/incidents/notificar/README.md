# notificar

- **Dueño:** Persona B
- **Qué hace:** Enruta por `NotificationRules`: SNS email + Pub/Sub (→ FCM). Dedup con TTL.
- **Consume:** regla EventBridge `IncidentStateChanged` (todas las transiciones, §10) e invocación directa de la SFN (`parts.shortage`; sirve para `report.daily`).
- **Detalle:** `Query notification-rules pk=EVENT#<event_type>` → `enabled` y `severity ≥ severity_min` → throttle `NTF#<event_type>#<rol>#<incident_id>[#<technician_id>]` en `idempotency` (TTL; `throttle_minutes = 0` = sin throttle) → contenido por `content_profile` → `push` (Pub/Sub REST con JWT RS256 firmado con stdlib, `gcp_auth.py`), `email` (SNS `{p}-alerts-{rol}`, atributos `zone`/`severity`), `dashboard` (nada).
- **Produce:** SNS, mensaje Pub/Sub `notificaciones`. Con `PUSH_MODE=direct` (`infra/incidents -var push_mode=direct`), invoca la Lambda `notify-push` en vez de publicar en Pub/Sub (plan B sin facturación GCP).
- **Cubre:** RF-10.1, RF-10.2, RF-10.5
- **Despliegue:** Fuera de la VPC.
- **Cómo probar:** `pytest services/incidents/notificar/tests`
