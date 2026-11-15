# notify_telegram

- **Dueño:** Persona B
- **Qué hace:** Envía a Telegram las transiciones de incidentes **críticos** (canal de guardia).
- **Consume:** regla EventBridge `{p}-telegram`: `IncidentStateChanged` con `detail.data.severity = critical` y `event_type` en `var.telegram_event_types` (por defecto `incident.detected`, `incident.assigned`, `incident.escalated`, `incident.resolved`).
- **Produce:** `sendMessage` de la Bot API (HTML, con diagnóstico IA si existe y botón "Abrir incidente" si `var.app_url` es https).
- **Detalle:** independiente de `notification-rules` y de `notificar`. Dedup `TG#<event_id>#<chat>` en `idempotency` (TTL 24 h) para no duplicar en reintentos de EventBridge; si falla un envío se libera la reserva, y si fallan todos se relanza (EventBridge reintenta, luego DLQ).
- **Configuración:** secreto `arquifusion/<stage>/telegram` = `{"bot_token": "...", "chat_ids": ["..."]}`. Lo carga `scripts/deploy_infra.sh` desde `.env.deploy`:
  ```
  TELEGRAM_BOT_TOKEN=123456:ABC...
  TELEGRAM_CHAT_ID=123456789          # varios: 123,-100987654321 (grupos empiezan con -100)
  ```
  Sin secreto, la Lambda omite el envío sin error.
- **Cubre:** RF-10.1, RF-10.2
- **Despliegue:** Fuera de la VPC (sale a api.telegram.org).
- **Cómo probar:** `pytest services/incidents/notify_telegram/tests`
