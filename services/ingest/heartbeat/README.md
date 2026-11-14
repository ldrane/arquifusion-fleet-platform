# heartbeat

- **Dueño:** Persona A
- **Qué hace:** Marca `silent` las máquinas sin lectura en más de 3× su intervalo.
- **Consume:** EventBridge Scheduler (cada 5 min)
- **Produce:** Evento `MachineSilent`
- **Cubre:** OBS-09
- **Despliegue:** Fuera de la VPC.
- **Cómo probar:** `pytest services/ingest/heartbeat/tests`
