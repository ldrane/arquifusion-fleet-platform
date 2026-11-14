# heartbeat

- **Dueño:** Persona A
- **Qué hace:** cada 5 min marca `status = silent` las máquinas sin lectura en más de 3 × `expected_interval_s` (60 s por defecto) y emite un único `MachineSilent` por silencio (escritura condicional sobre `last_seen_at`). Si no puede emitir, revierte la marca.
- **Consume:** EventBridge Scheduler, tabla `{p}-machines`.
- **Produce:** `machines.status = silent` (+ `silent_since`, `status_before_silent`), evento `MachineSilent` (contratos.md §3).
- **Cubre:** OBS-09, RF-05.
- **Despliegue:** zip + capa `{p}-a-common` (`infra/ingest/heartbeat.tf`), fuera de la VPC.
- **Cómo probar:** `.venv/bin/pytest services/ingest/heartbeat`
