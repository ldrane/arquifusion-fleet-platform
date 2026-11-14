# combustible

- **Dueño:** Persona A
- **Qué hace:** rama de `AnalisisDiario`. L/h en operación y L/t, comparación con la mediana de su tipo y con su propio historial (días 31-90), aumento progresivo (pendiente ≥ 2 %/semana en 30 días) y causas probables por reglas (sobrecarga, RPM, temperatura, ralentí, desgaste).
- **Consume:** estadísticas diarias de Athena (`daily_machine_stats.sql`).
- **Produce:** `insights` `fuel#7d` y `fuel#30d` (GET /v1/analytics/fuel, + campo `zone`).
- **Cubre:** RF-07.1 a RF-07.4.
- **Despliegue:** zip + `analytics_common` + capa común (`infra/ingest/analytics.tf`).
- **Cómo probar:** `pytest services/analytics/combustible/tests`
