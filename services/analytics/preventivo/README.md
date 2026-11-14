# preventivo

- **Dueño:** Persona A
- **Qué hace:** rama de `AnalisisDiario`. Próxima fecha de mantenimiento por condición: horas reales desde el último preventivo × intensidad (carga, temperatura), adelantada si el health score es bajo. Marca `overdue` (atrasado o health < 40), `unnecessary` (el calendario fijo lo pide en ≤ 14 días pero la condición permite > 30) y `on_track`.
- **Consume:** estadísticas diarias de Athena (`daily_machine_stats.sql`), tablas `machines` y `maintenance-records`.
- **Produce:** `insights` `maintenance_plan` (GET /v1/maintenance/plan, + campo `zone`) y `next_maintenance_at` en `machines`.
- **Cubre:** RF-03.1, RF-03.2, RF-03.3.
- **Despliegue:** zip + `analytics_common` + capa común (`infra/ingest/analytics.tf`).
- **Cómo probar:** `pytest services/analytics/preventivo/tests`
