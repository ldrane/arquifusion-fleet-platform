# ArquiFusion Fleet Platform

Plataforma serverless y multinube (AWS + GCP) para la telemetría de maquinaria pesada: detección de anomalías con IA, mantenimiento predictivo, asignación de técnicos, repuestos y comunicación por incidente.

> Grupo 27 · RootAccess · Hackathon ArquiFusion

## Empieza aquí
1. [`docs/division-trabajo-backend.md`](docs/division-trabajo-backend.md): quién hace qué, hitos y buenas prácticas.
2. [`contracts/`](contracts/): `openapi.yaml` (REST) y `contratos.md` (eventos, Pub/Sub, Firestore). **Fuente de verdad.**
3. [`CONTRIBUTING.md`](CONTRIBUTING.md): ramas, commits, Definition of Done y setup local.

## Estructura

```
contracts/                 Contratos (fuente de verdad) + fixtures/ de ejemplo por interfaz
docs/                      Contexto, rúbrica, requerimientos, arquitectura, división del trabajo
infra/                     Terraform, un state por stack
  base/                    (B) DynamoDB, EventBridge, API Gateway, Cognito, SNS, secretos
  ingest/                  (A) SQS, procesar, Firehose, lake, Athena, SFN de analítica
  incidents/               (B) SFN GestionIncidente y Lambdas de incidente
  query/                   (C) api-lectura, replicar, VPC
  gcp/                     (C + B) Firestore, Pub/Sub, Cloud Function
services/
  shared/                  (B) librería común: respuestas, errores, correlation_id, RBAC
  ingest/                  (A) procesar, heartbeat
  ai/                      (A) ia_gemini
  analytics/               (A) ramas de AnalisisDiario, retrain, sfn/
  incidents/               (B) api_comandos, scoring, correlacion, notificar, auditoria, sfn/
  query/                   (C) api_lectura, replicar
gcp/
  functions/notify_bridge/ (B) Pub/Sub → FCM · Firestore actions → /bridge/events
  firestore/               (C) README de Firestore (las reglas están en infra/gcp/firestore.rules)
simulator/                 (A) Simulador de flota y escenarios
scripts/                   seed.py (C), smoke_golden_path.sh (todos)
frontend/                  (C) App web/móvil
```

Cada servicio tiene `README.md` (dueño, qué consume y produce, RF que cubre), `handler.py`, `service.py`, `requirements.txt` y `tests/`.

## Dueños
| Persona | Dominio |
|---|---|
| **A** | Datos e IA: simulador, ingesta, `procesar`, `ia-gemini`, analítica, ML |
| **B** | Orquestación: infra base, `shared`, `GestionIncidente`, comandos, notificaciones, puente GCP |
| **C** | Consulta y tiempo real: seeds, `api-lectura`, `replicar`, Firestore, frontend |

## Golden path (demo)
Simulador → `POST /telemetry` → SQS → `procesar` → `AnomalyDetected` → Step Functions `GestionIncidente` → `ia-gemini` + `scoring` → `notificar` (SNS + Pub/Sub → FCM) → `ack` → chat Firestore → `resolve` → resumen IA → `closed`.
