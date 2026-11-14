# replicar

- **Dueño:** Persona C
- **Qué hace:** DynamoDB Streams → Firestore con el mismo esquema que la API (`query_common.items`): `machines/{machine_id}`, `incidents/{incident_id}` (solo `sk = META`, ignora `EVT#`, #26), `technicians/{technician_id}` (con `location.zone` siempre, #11).
- **Consume:** Streams `NEW_AND_OLD_IMAGES` de `{p}-machines`, `{p}-incidents`, `{p}-technicians`; secreto `arquifusion/{stage}/gcp/service-account`.
- **Produce:** documentos Firestore (Admin, vía REST `documents:commit`, lotes de 500). Nunca replica `ack_token`, `resolve_token`, `execution_arn`.
- **Costo:** las máquinas se escriben al instante si cambia algo visible; si solo cambia ruido (`last_seen_at`, horas, ubicación, salud < 5 puntos) como máximo cada `REPLICA_HEARTBEAT_S` (300 s).
- **Errores:** relanza → el event source mapping reintenta con bisect y deja el lote en la DLQ `{p}-replicar-dlq`.
- **Cubre:** RF-05, RF-15.3, RF-16, MH-HA-03, MH-MC-02
- **Despliegue:** `infra/query`, fuera de la VPC (sale a GCP).
- **Cómo probar:** `python -m pytest services/query -q`
