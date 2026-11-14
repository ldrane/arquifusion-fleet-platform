# replicar

- **Dueño:** Persona C
- **Qué hace:** DynamoDB Streams → Firestore (`machines`, `incidents`, `technicians`) con el mismo esquema que la API.
- **Consume:** Streams de `Machines`, `Incidents`, `Technicians`
- **Produce:** Colecciones Firestore
- **Cubre:** RF-05, RF-15.3, MH-HA-03
- **Despliegue:** Fuera de la VPC (sale a GCP).
- **Cómo probar:** `pytest services/query/replicar/tests`
