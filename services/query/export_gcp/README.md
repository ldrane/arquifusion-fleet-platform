# export_gcp

- **Dueño:** Persona C
- **Qué hace:** réplica DR multinube (TAREA-13). AnalisisDiario la invoca al final (estado `ExportarGCP`) para copiar el day-lake a BigQuery (sandbox, sin facturación) con *load jobs* multipart: el CSV de Athena -> `daily_machine_stats`, los incidentes cerrados de las últimas 24 h -> `incidents` (solo campos públicos, sin tokens) y los insights `kpis#7d`/`kpis#30d` `LATEST` -> `kpis_daily`.
- **Consume:** `athena.get_query_execution` (OutputLocation del CSV en S3), tablas `incidents` (`sk = META`, `closed_at` en 24 h) e `insights`, y la service account `arquifusion/<stage>/gcp/service-account` de Secrets Manager.
- **Produce:** filas en el dataset BigQuery `arquifusion_<stage>` (proyecto de la SA). Devuelve `{"tables", "job_ids", "errors"}`; un fallo de GCP queda en `errors` y **no** lanza (DR best-effort).
- **Cubre:** TAREA-13 (memoria y DR multinube) + tablero Looker Studio de Gerencia.
- **Despliegue:** stack **query** (`infra/query/main.tf`); comparte la layer de C (`google-auth`). Fuera de VPC.
- **Cómo probar:** `pytest services/query/export_gcp/tests`
