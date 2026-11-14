# repuestos

- **Dueño:** Persona A
- **Qué hace:** Rama de `AnalisisDiario`: demanda de repuestos por almacén, stock mín./máx., consumo irregular.
- **Consume:** Resultados Athena
- **Produce:** `Inventory.recommended_*`
- **Cubre:** RF-04
- **Despliegue:** Fuera de la VPC.
- **Cómo probar:** `pytest services/analytics/repuestos/tests`
