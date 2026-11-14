# infra/incidents

- **Dueño:** Persona B
- **Contiene:** SFN `GestionIncidente` (Standard + JSONata), reglas EventBridge, Lambdas `api-comandos`, `incidente`, `scoring-tecnicos`, `correlacion-zona`, `notificar`, `auditoria`, DLQ de eventos y alarmas.
- **State:** `s3://<bucket-tfstate>/arquifusion/incidents/terraform.tfstate`.
- **Requisitos previos:** `infra/base` (bus, API, tablas, SNS) e `infra/ingest` (publica `/arquifusion/{stage}/lambda/ia-gemini/arn` en SSM).
- **Desplegar:** `terraform -chdir=infra/incidents init -backend-config=../backend.hcl && terraform -chdir=infra/incidents apply -var stage=<stage>`
  - Demo con escalamiento rápido: `-var ack_timeout_s=120 -var ack_timeout_critical_s=90`.

## Cableado de eventos (contratos.md §3, §10)

| Regla (`{p}-…`) | Patrón | Destino |
|---|---|---|
| `anomaly` | `arquifusion.processor` / `AnomalyDetected`, severidad medium+ | SFN `{p}-gestion-incidente` |
| `silent` | `arquifusion.heartbeat` / `MachineSilent` | SFN (severidad `low`, especialidad `electrica`) |
| `notify` | `arquifusion.incident` / `IncidentStateChanged` | Lambda `notificar` |
| `audit` | los tres anteriores | Lambda `auditoria` (`audit-events` + historial `EVT#`) |

Todos los targets tienen retry + DLQ `{p}-incidents-events-dlq` (alarma a `{p}-platform-alarms`).

## Flujo de la SFN (`services/incidents/sfn/gestion_incidente.asl.json`)

`Inicio` (INC-ULID) → `ReclamarMaquina` (UpdateItem condicional `open_incident_id`, dedup) → `CrearIncidente` (PutItem, `detected`)
→ `EmitirDetectado` → `Enriquecer` (Parallel: contexto+`candidate_parts` → ia-gemini `diagnose` ‖ `correlacion` → `common_cause`)
→ `GuardarEnriquecimiento` (`ai_diagnosis`, `required_specialty` §8.2, stock) → `parts.shortage` si falta
→ SLA por severidad → `Puntuar` (§8.3) → `Asignar` → `EmitirAsignado` → `EsperarAceptacion` (`ack_token`, timeout)
→ accept: `Aceptar` (UpdateItem) → `EmitirEnAtencion` → `EsperarResolucion` (`resolve_token`) → `Resolver` (downtime)
→ `EmitirResuelto` → `ResumenIA` → `Cerrar` (corrective + inventario + libera máquina) → `EmitirCerrado`.
reject → siguiente candidato · reassign (POST assign) → `AsignarManual` · timeout → `Escalar` (máx. `max_escalations`)
→ sin candidatos → `EsperarAsignacionManual` (token en `detected`/`assigned`, #16).

Integraciones SDK directas: DynamoDB (`updateItem`/`putItem`) y EventBridge (`putEvents`). La Lambda `incidente` solo
hace los pasos con estructuras anidadas (diagnóstico, candidatos, cierre).
