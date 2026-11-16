# ArquiFusion Fleet Platform

Plataforma serverless y multinube (AWS + GCP) para la telemetría de maquinaria pesada: detección de anomalías con IA, mantenimiento predictivo, asignación de técnicos, repuestos y comunicación por incidente.

> Grupo 27 · RootAccess · Hackathon ArquiFusion

## Empieza aquí
1. [`diagrama/Arquitectura_Solucion_ArquiFusion.drawio`](diagrama/Arquitectura_Solucion_ArquiFusion.drawio): diagrama de arquitectura (AWS + GCP), y [`docs/arquitectura-solucion-aws.md`](docs/arquitectura-solucion-aws.md) con los flujos.
2. [`contracts/`](contracts/): `openapi.yaml` (REST) y `contratos.md` (eventos, Pub/Sub, Firestore). **Fuente de verdad.**
3. [`CONTRIBUTING.md`](CONTRIBUTING.md): ramas, commits, Definition of Done y setup local.

## Estructura

```
contracts/                 Contratos (fuente de verdad) + fixtures/ de ejemplo por interfaz
diagrama/                  Diagrama de arquitectura (draw.io)
docs/                      Arquitectura (flujos), requerimientos, costos, concurrencia, smoke tests, pitch
infra/                     Terraform, un state por stack
  modules/lab_s3_bucket/   Bucket S3 compatible con el Learner Lab (evita `aws_s3_bucket`)
  base/                    (B) DynamoDB, EventBridge, API Gateway, Cognito, SNS, secretos
  ingest/                  (A) SQS, procesar, Firehose, lake, Athena, SFN de analítica, sim-driver
  incidents/               (B) SFN GestionIncidente, Lambdas de incidente y VPC aislada de auditoría
  query/                   (C) api-lectura, replicar, export-gcp
  gcp/                     (C + B) Firestore, Pub/Sub, Cloud Function, BigQuery (DR)
services/
  shared/                  (B) librería común: respuestas, errores, correlation_id, RBAC
  ingest/                  (A) procesar, heartbeat, sim_driver
  ai/                      (A) ia_gemini
  analytics/               (A) ramas de AnalisisDiario, retrain, sfn/
  incidents/               (B) api_comandos, scoring, correlacion, notificar, notify_push,
                               notify_telegram, auditoria, incidente, sfn/
  query/                   (C) api_lectura, replicar, export_gcp
gcp/
  functions/notify_bridge/ (B) Pub/Sub → FCM · Firestore actions → /bridge/events
  firestore/               (C) README de Firestore (las reglas están en infra/gcp/firestore.rules)
simulator/                 (A) Simulador de flota y escenarios
scripts/                   seed.py (C), check_all.sh, demo_preflight.sh, demo_reset.py, smoke_golden_path.sh
frontend/                  (C) App web/móvil (React + PWA, hosting en Firebase Hosting)
```

Cada servicio tiene `README.md` (dueño, qué consume y produce, RF que cubre), `handler.py`, `service.py`, `requirements.txt` y `tests/`.

## Dueños
| Persona | Dominio |
|---|---|
| **A** | Datos e IA: simulador, ingesta, `procesar`, `ia-gemini`, analítica, ML |
| **B** | Orquestación: infra base, `shared`, `GestionIncidente`, comandos, notificaciones, puente GCP |
| **C** | Consulta y tiempo real: seeds, `api-lectura`, `replicar`, Firestore, frontend |

## Golden path (demo)
Simulador (o `sim-driver` serverless) → `POST /telemetry` → SQS → `procesar` → `AnomalyDetected` → Step Functions `GestionIncidente` → `ia-gemini` + `scoring` → `notificar` (SNS + `notify-push` → FCM + `notify-telegram`) → `ack` → chat Firestore → `resolve` → resumen IA → `closed` → `auditoria` (append-only) + `replicar` (Firestore) + `export-gcp` (BigQuery/Looker).
