# Contrato DynamoDB — tablas con datos maestros (propuesta de C, aprobar con B en H0)

> Estado: **APROBADO** (rev. 2026-11-14, seed v2; ver `contratos.md` §9). B es dueño de las tablas (`infra/base`); C es dueña del seed (`scripts/seed.py`).
> Si B elige otras claves, se cambia solo `KEY_SCHEMA` en `scripts/seed.py` y esta página.

## Reglas comunes

- Nombre: `arquifusion-{stage}-{tabla}` (por ejemplo `arquifusion-dev-machines`).
- On-demand, **PITR ON**, **Streams `NEW_AND_OLD_IMAGES`** (los usan `replicar` y `auditoria`).
- Clave genérica: `pk` (S) + `sk` (S). `machines` e `inventory` siguen el formato de contratos.md §9 (Persona A); el resto usa prefijo de entidad (`TECH#TEC-07`).
- Cada ítem guarda **también los campos de dominio en limpio** (`machine_id`, `zone`, ...), con los mismos nombres que el OpenAPI.
  `api-lectura` y `replicar` quitan `pk`, `sk` y `entity` antes de responder o replicar, así el esquema de la API y el de Firestore es el mismo.
- `entity` indica el tipo de ítem cuando una tabla guarda varios (Catalog).
- Los GSIs usan **atributos de dominio**, no claves sintéticas: nadie tiene que mantener `gsi1pk` al actualizar `status`.

## Tablas

| Tabla | `pk` | `sk` | GSI | Quién escribe |
|---|---|---|---|---|
| `machines` | `<operation_id>#<machine_id>` (ej. `OP-01#EX-023`, contratos.md §9) | `META` | `by_zone`: `zone` → `machine_id` | C (seed), A (`status`, `severity`, `health_score`, `last_seen_at`, `top_factors`, `model_version`), A7 (`next_maintenance_at`), B (`open_incident_id`) |
| `technicians` | `TECH#<technician_id>` | `META` | `by_zone`: `zone` → `technician_id` | C (seed), B (`available`, `location`, `current_load`) |
| `catalog` | `COMPONENT#<component_id>` / `MODEL#<model_id>` | `META` | — | C (seed) |
| `inventory` | `<location_id>` (ej. `WH-01`, contratos.md §9) | `<component_id>` (ej. `CMP-014`) | `by_component`: `component_id` → `warehouse_id` | C (seed), B (descuento al cierre), A7 (`recommended_*`) |
| `warehouses` | `<warehouse_id>` (ej. `WH-04`) | `META` | — | C (seed). Lo leen la SFN (B, rama stock) y la analítica (A). 4 almacenes, uno por zona |
| `notification-rules` | `EVENT#<event_type>` | `ROLE#<role>` | — | C (seed); lo lee `notificar` (B) con `Query pk = EVENT#incident.detected` |

`Incidents`, `MachineState`, `Anomalies`, `Idempotency`, `AuditEvents`, `MaintenanceRecords` e `Insights` no tienen seed: las define B en `infra/base` (A y B escriben).

## Forma de los ítems (ver `contracts/fixtures/seed/*.json`)

- **Machine**: campos de `Machine`/`MachineDetail` del OpenAPI + `operation_id`, `zone` (copia de `location.zone` para el GSI), `home_location`, `expected_interval_s` (= 60; heartbeat declara silencio a 3× = 180 s), `seed_version`.
  `model`, `type`, `zone`, `home_location` y `expected_interval_s` no los sobrescribe nadie (contratos.md §9).
  En los fixtures `last_seen_at`, `open_incident_id`, `model_version`, `rul_hours` y `failure_probability` valen `null`.
  **En DynamoDB esos atributos no se escriben** (`seed.py` omite los `None`): un atributo `NULL` cuenta como existente para
  `attribute_exists`/`attribute_not_exists`. Así heartbeat (A) ignora las máquinas sin lectura y el dedup de `procesar` funciona.
- **Technician**: `Technician` del OpenAPI + `user_id` (= `cognito:username`, ej. `u-tec-07`), `zone`, `home_warehouse_id` (el almacén de su zona).
  `location.zone` siempre = `zone` (B lo conserva al actualizar la ubicación). El usuario Cognito del técnico lleva `custom:technician_id = technician_id`.
- **Component** (`entity=catalog`): `component_id`, `name`, `specialty` (enum de técnicos), `compatible_models[]`, `cost_usd`, `lead_time_days`.
- **MachineModel** (`entity=machine_models`): `model_id`, `brand`, `type`, `payload_t`, `maintenance_interval_h`, `nominal{variable: [media, desv]}`, `component_ids[]`.
  Rama "stock" de la SFN (B): `GetItem MODEL#<model>` → `component_ids` → `Query by_component` en Inventory.
  Diagnóstico (B → A): `component_ids` + `COMPONENT#…` → `candidate_parts[{component_id, name, specialty}]` (contratos.md §8.1).
  La analítica (A) lee `maintenance_interval_h`, `payload_t` y `nominal` de aquí (no usa constantes propias).
- **InventoryItem**: `InventoryItem` del OpenAPI + `location_id` (= `warehouse_id`, lo lee A), `warehouse_name`, `zone`.
- **Warehouse**: `warehouse_id`, `name`, `zone`, `location{lat, lon, zone}`.
- **NotificationRule**: `event_type`, `role`, `severity_min`, `channels[]` (`push`, `email`, `dashboard`), `content_profile` (`technical`, `operational`, `executive`), `throttle_minutes`, `enabled`.
  `event_type` (tabla transición → `event_type` en contratos.md §10): `incident.detected`, `incident.assigned`, `incident.in_progress`, `incident.escalated`,
  `incident.resolved`, `incident.closed`, `machine.silent`, `parts.shortage`, `report.daily`.

## Snippet Terraform sugerido para B (`infra/base`)

```hcl
resource "aws_dynamodb_table" "machines" {
  name         = "arquifusion-${var.stage}-machines"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"
  point_in_time_recovery { enabled = true }

  dynamic "attribute" {
    for_each = ["pk", "sk", "zone", "machine_id"]
    content {
      name = attribute.value
      type = "S"
    }
  }

  global_secondary_index {
    name            = "by_zone"
    hash_key        = "zone"
    range_key       = "machine_id"
    projection_type = "ALL"
  }
}
# technicians: igual con technician_id · inventory: GSI by_component (component_id, warehouse_id)
# catalog, warehouses y notification-rules: solo pk/sk
```

## Tablas de B y A (sin seed)

| Tabla | `pk` | `sk` | GSI | Notas |
|---|---|---|---|---|
| `incidents` | `INC#<incident_id>` | `META` · `EVT#<ts>#<event_id>` | `by_machine`: `machine_id` → `detected_at` · `by_status`: `status` → `detected_at` | Escribe B. META guarda `machine_id` (escalar, principal) **y** `machine_ids[]`, `zone`, `ack_token`, `resolve_token`, `execution_arn`, `parent_incident_id`, `child_incident_ids`, `correlation_id`. Los `EVT#` no llevan `incident_id`/`status`/`machine_id`/`detected_at` en la raíz (contratos.md §9.1) |
| `machine-state` | `<machine_id>` | `AGG#1h#<ts>` · `BASELINE` · `LAST` | — | Escribe A. TTL `expires_at` |
| `anomalies` | `<machine_id>` | `<detected_at>#<anomaly_id>` | `by_zone`: `zone` → `detected_at` | Escribe A. `detected_at` = timestamp de la lectura (ISO 8601). Sin `gsi1pk`/`gsi1sk` |
| `idempotency` | `<machine_id>#<timestamp>` · `NTF#<event_type>#<role>#<id>` | — (solo `pk`) | — | Escribe A (lecturas, 24 h) y B (throttle de notificar). TTL `expires_at` |
| `audit-events` | `<entidad>#<id>` | `<ts>#<event_id>` | — | Escribe B. Solo PutItem, nunca modificar |
| `maintenance-records` | `<machine_id>` | `<performed_at>#<record_id>` | — | Escribe B (correctivo al cerrar el incidente). Atributos: `record_id`, `machine_id`, `zone`, `type` (`preventive`/`corrective`), `performed_at`, `technician_id`, `incident_id?`, `operating_hours`, `components[{component_id, quantity}]`, `cost_usd`, `notes?`. Lee A (Scan) y C (Query por máquina, timeline) |
| `insights` | `<kind>` (ej. `maintenance_plan`, `kpis#7d`) | `LATEST` · `YYYY-MM-DD` · en `kpis#*` además `LATEST#<zone>` / `YYYY-MM-DD#<zone>` | — | Escribe A, lee C. `data` = `data` del endpoint del OpenAPI, + `generated_at`, `correlation_id` |

## Reglas

1. **Sin incidentes duplicados.** `procesar` (A) actualiza `machines` con la condición "solo si no existe `open_incident_id`". Si se cumple, guarda el ID y emite `AnomalyDetected`. El workflow `GestionIncidente` (B) borra ese campo al cerrar el incidente. Nunca se escribe `open_incident_id = NULL`: se omite o se elimina.
2. **Tokens secretos.** `ack_token`, `resolve_token` y `execution_arn` nunca salen por la API ni se replican a Firestore. `api-lectura` y `replicar` deben quitarlos.
