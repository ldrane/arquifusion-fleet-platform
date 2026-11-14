# productividad

- **Dueño:** Persona A
- **Qué hace:** rama de `AnalisisDiario`. Utilización (lecturas en operación / totales), clasificación `underused` (< 40 %) / `overused` (≥ 85 % o ≥ 18 h/día), costo por hora (combustible + mantenimiento), cuadrante productividad × costo frente a la mediana de su tipo y sugerencia de redistribución entre zonas.
- **Consume:** estadísticas diarias de Athena y `maintenance-records` (costos).
- **Produce:** `insights` `productivity#7d` y `productivity#30d` (GET /v1/analytics/productivity, + campo `zone`).
- **Cubre:** RF-08.1 a RF-08.4.
- **Despliegue:** zip + `analytics_common` + capa común (`infra/ingest/analytics.tf`).
- **Cómo probar:** `pytest services/analytics/productividad/tests`
