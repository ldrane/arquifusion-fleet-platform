# Contrato DynamoDB — ArquiFusion

Base: `docs/arquitectura-solucion-aws.md §2.6`. Este archivo fija los detalles que ahí quedan abiertos.

## Reglas generales
- Todas las tablas: on-demand, PITR activado, Streams `NEW_AND_OLD_IMAGES`.
- Nombre físico: `arquifusion-{stage}-<tabla>` (minúsculas y guiones).
- Claves: `pk` y `sk`. Índices: `gsi1pk/gsi1sk` y `gsi2pk/gsi2sk`.
- Si la columna `sk` dice "—", la tabla solo tiene `pk` (sin range key).
- Fechas en ISO 8601 UTC.

## Tablas

| Tabla | pk | sk | Índices | Extra |
|---|---|---|---|---|
| machines | `OP-01#<machine_id>` | `META` | GSI1: zona → estado | `open_incident_id` (anti duplicados) |
| machine-state | `<machine_id>` | `AGG#1h#<ts>` · `BASELINE` · `LAST` | — | TTL `expires_at` |
| idempotency | `<machine_id>#<timestamp>` | — | — | TTL `expires_at` (24 h) |
| anomalies | `<machine_id>` | `<ts>#<anomaly_id>` | GSI1: zona#fecha → ts | |
| incidents | `<incident_id>` | `META` · `EVT#<ts>` | GSI1: machine_id → fecha de detección · GSI2: estado#severidad → ts | `ack_token`, `resolve_token`, `execution_arn`, `parent_incident_id`, `child_incident_ids`, `correlation_id` |
| technicians | `<technician_id>` | `META` | GSI1: disponible → zona | |
| inventory | `<warehouse_id>` | `<component_id>` | GSI1: component_id → almacén | |
| catalog | `<component_id>` o `<model_id>` | `META` · `COMPAT#…` | — | |
| notification-rules | `<role>` | `<severidad>#<tipo_evento>` | — | |
| audit-events | `<entidad>#<id>` | `<ts>#<event_id>` | — | Solo PutItem, nunca modificar |

## Reglas
1. **Sin incidentes duplicados.** `procesar` (Persona A) actualiza `machines` con la condición "solo si no existe `open_incident_id`". Si se cumple, guarda el ID y emite `AnomalyDetected`. El workflow `GestionIncidente` (Persona B) borra ese campo al cerrar el incidente.
2. **Tokens secretos.** `ack_token`, `resolve_token` y `execution_arn` nunca salen por la API ni se replican a Firestore.