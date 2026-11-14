# api_lectura

- **Dueño:** Persona C
- **Qué hace:** Todos los GET de `/v1/*` (máquinas, incidentes, técnicos, inventario, analítica) con paginación y RBAC.
- **Consume:** API Gateway `/v1/*` (JWT)
- **Produce:** Respuestas según `contracts/openapi.yaml`
- **Cubre:** RF-05, RF-11, RF-02.3
- **Despliegue:** Dentro de la VPC si H0 lo permite.
- **Cómo probar:** `pytest services/query/api_lectura/tests`
