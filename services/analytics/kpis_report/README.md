# kpis_report

- **Dueño:** Persona A
- **Qué hace:** cierre de `AnalisisDiario`. KPIs de flota para 7 y 30 días (disponibilidad, MTBF, MTTR, incidentes abiertos, máquinas en riesgo, utilización, combustible USD/t) y resumen ejecutivo pedido a `ia-gemini` (`executive_report`), con resumen determinista si la IA falla.
- **Consume:** estadísticas diarias de Athena, tablas `machines` e `incidents`, resultado de las 4 ramas (`branches`).
- **Produce:** `insights` `kpis#7d`, `kpis#30d` (GET /v1/analytics/kpis) y `report#daily` (GET /v1/reports/latest).
- **Cubre:** RF-10.3, RF-11.4, RF-13.3.
- **Despliegue:** zip + `analytics_common` + capa común (`infra/ingest/analytics.tf`).
- **Cómo probar:** `pytest services/analytics/kpis_report/tests`
