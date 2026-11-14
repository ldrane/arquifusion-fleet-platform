# correlacion

- **Dueño:** Persona B
- **Qué hace:** Lambda `correlacion-zona` (§8.4): ≥3 máquinas con anomalías en la zona en 15 min (GSI `by_zone` de `anomalies`) → el incidente padre es el incidente abierto más antiguo del grupo (se le agregan `child_incident_ids` y `machine_ids`); si no hay, este incidente queda como padre.
- **Consume:** Invocación desde SFN
- **Produce:** `parent_incident_id`
- **Cubre:** RF-12
- **Despliegue:** Fuera de la VPC.
- **Cómo probar:** `pytest services/incidents/correlacion/tests`
