# notificar

- **Dueño:** Persona B
- **Qué hace:** Enruta por `NotificationRules`: SNS email + Pub/Sub (→ FCM). Dedup con TTL.
- **Consume:** Invocación desde SFN (Map por rol)
- **Produce:** SNS, mensaje Pub/Sub `notificaciones`
- **Cubre:** RF-10.1, RF-10.2, RF-10.5
- **Despliegue:** Fuera de la VPC.
- **Cómo probar:** `pytest services/incidents/notificar/tests`
