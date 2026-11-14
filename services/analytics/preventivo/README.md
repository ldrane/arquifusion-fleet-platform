# preventivo

- **Dueño:** Persona A
- **Qué hace:** Rama de `AnalisisDiario`: próxima fecha de mantenimiento por condición.
- **Consume:** Resultados Athena
- **Produce:** `Machines.next_maintenance`, tabla `Insights`
- **Cubre:** RF-03
- **Despliegue:** Fuera de la VPC.
- **Cómo probar:** `pytest services/analytics/preventivo/tests`
