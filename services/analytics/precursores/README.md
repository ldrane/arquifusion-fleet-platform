# precursores

- **Dueño:** Persona A
- **Qué hace:** rama de `AnalisisDiario` (TAREA-12). Firmas pre-falla: para cada incidente cerrado/resuelto de los últimos 90 días busca la primera anomalía de su máquina en las 72 h previas (`first_signal`), agrupa por modelo y calcula por variable dominante la proporción de fallas precedidas (`share`), la mediana de anticipación (`median_lead_time_h`) y la mediana del z-score (`median_z`).
- **Consume:** tablas `incidents` (META `closed`/`resolved`), `anomalies` (`Query pk=<machine_id>`) y `machines` (modelo por máquina).
- **Produce:** `insights` `precursors` (GET /v1/analytics/precursors): `[{"model", "n_incidents", "signatures", "headline"}]`, ordenada por `n_incidents`; ignora los modelos con menos de 3 incidentes.
- **Cubre:** TAREA-12 (profundidad predictiva).
- **Despliegue:** zip + `analytics_common` + capa común (`infra/ingest/analytics.tf`).
- **Cómo probar:** `pytest services/analytics/precursores/tests`
