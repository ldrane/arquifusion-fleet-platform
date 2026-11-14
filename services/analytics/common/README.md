# analytics_common

- **Dueño:** Persona A
- **Qué hace:** utilidades compartidas por las Lambdas de `AnalisisDiario` y `Reentrenamiento`: lectura de resultados de Athena, estadísticas diarias por máquina, lectura y escritura en DynamoDB e ítems de `insights`.
- **Consume:** resultados de Athena de `sql/daily_machine_stats.sql` (una sola consulta por ejecución, compartida por las 4 ramas y los KPIs).
- **Produce:** nada por sí misma.
- **Cubre:** RF-03, RF-04, RF-07, RF-08, RF-10.3, RF-13.
- **Empaquetado:** Terraform la copia dentro del zip de cada Lambda de analítica (`infra/ingest/analytics.tf`) y el Dockerfile de `retrain` la copia a la imagen.
- **Cómo probar:** `pytest services/analytics/common/tests`
