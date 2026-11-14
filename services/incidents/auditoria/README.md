# auditoria

- **Dueño:** Persona B
- **Qué hace:** DynamoDB Streams → tabla `AuditEvents` append-only.
- **Consume:** Streams de `Incidents`, `Machines`
- **Produce:** `AuditEvents`
- **Cubre:** RNF-15, TRZ-02
- **Despliegue:** Dentro de la VPC si H0 lo permite.
- **Cómo probar:** `pytest services/incidents/auditoria/tests`
