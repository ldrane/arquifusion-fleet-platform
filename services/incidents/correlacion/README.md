# correlacion

- **Dueño:** Persona B
- **Qué hace:** Lambda `correlacion-zona`: ≥3 máquinas en 30 min → incidente padre.
- **Consume:** Invocación desde SFN
- **Produce:** `parent_incident_id`
- **Cubre:** RF-12
- **Despliegue:** Fuera de la VPC.
- **Cómo probar:** `pytest services/incidents/correlacion/tests`
