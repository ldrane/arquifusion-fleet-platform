# repuestos

- **Dueño:** Persona A
- **Qué hace:** rama de `AnalisisDiario`. Ranking de componentes por consumo en 90 días con detección de consumo irregular, y pronóstico por almacén para 7/30/90 días: consumo histórico repartido según las máquinas activas de cada zona + demanda planificada (máquinas con mantenimiento próximo o health < 50, con la mezcla de componentes histórica de su tipo). Stock mín. = demanda en el lead time + seguridad al 95 %; máx. = mín. + 30 días.
- **Consume:** Athena (máquinas activas por zona), tablas `machines`, `maintenance-records`, `inventory` (con `zone` opcional por almacén) y `catalog` (`lead_time_days`).
- **Produce:** `insights` `parts_ranking` y `parts_forecast#{7,30,90}` (GET /v1/parts/*).
- **Cubre:** RF-04.1 a RF-04.6.
- **Despliegue:** zip + `analytics_common` + capa común (`infra/ingest/analytics.tf`).
- **Cómo probar:** `pytest services/analytics/repuestos/tests`
