# División del trabajo de backend y microservicios: ArquiFusion Fleet Platform

> Grupo 27 · RootAccess. Fuentes: `contratos.md`, `openapi.yaml`, `arquitectura-solucion-aws.md`, `requerimientos.md`, `rubrica.md`.
> Objetivo: que 3 personas trabajen **en paralelo y sin bloquearse**. Cada una es dueña de un dominio completo, desde su infraestructura hasta su código y sus pruebas, y se comunica con las demás **solo a través de los contratos**.

---

## 0. Resumen

| | **Persona A: Datos e IA** | **Persona B: Orquestación de incidentes** | **Persona C: Consulta, tiempo real y frontend** |
|---|---|---|---|
| Rol | Del sensor a la anomalía | De la anomalía al incidente cerrado | De los datos a la pantalla |
| Carga backend | Alta | Alta | **Baja-media** (también lleva el frontend) |
| Lambdas | `procesar`, `heartbeat`, `ia-gemini`, lambdas de `AnalisisDiario` y `Reentrenamiento` | `api-ack` (→ `api-comandos`), `scoring-tecnicos`, `correlacion-zona`, `notificar`, `auditoria` | `api-lectura`, `replicar` |
| Step Functions | `AnalisisDiario`, `Reentrenamiento` | **`GestionIncidente`** (la central de la demo) | — |
| GCP | Vertex AI / Gemini | Pub/Sub + Cloud Function (FCM y bridge) | Proyecto GCP, Firestore + Security Rules, custom token |
| Otros | Simulador, SQS, Firehose, lake S3, Glue, Athena, modelo IsolationForest | IaC base (Terraform), EventBridge, API Gateway, Cognito, SNS, librería `shared/` | Seeds de datos maestros, colecciones Firestore, cliente API del front |
| Rúbrica que asegura | IA (3), Persistencia/HA (2), Serverless (2) | Step Functions (2), Arquitectura (3), Problemas resueltos (3) | 2+ nubes (3), Problemas resueltos (3), Pitch/demo (2) |

**Golden path de la demo** (prioridad absoluta, ver §5): simulador → `procesar` (A) → `AnomalyDetected` → `GestionIncidente` (B) → `ia-gemini` (A) → `notificar` (B) → Firestore/FCM (B + C) → `ack`/`resolve` (B) → mapa, cola y chat en vivo (C).

---

## 1. Persona A: Datos e IA (ingesta, detección, analítica)

**Misión:** convertir la telemetría cruda en anomalías explicables y en insights. Es dueña del "cerebro" de la plataforma.

### 1.1 Responsabilidades

| # | Entregable | Contrato que respeta | RF / RNF | Prioridad |
|---|---|---|---|---|
| A1 | **Simulador** (Python local): 50-100 máquinas de 5 tipos en 3-5 zonas, lotes ≤100, los 5 escenarios inyectables (degradación, falla súbita, combustible, grupal por zona, ociosa/sobreexplotada) por flag CLI | `POST /telemetry` (`openapi.yaml`) | RF-01, §5.6 | **Must** |
| A2 | Integración directa **API Gateway → SQS** `ingest` + DLQ (`maxReceiveCount=3`) + request validator JSON Schema | `POST /telemetry` → `202` | RF-01.1/01.3, RNF-07 | **Must** |
| A3 | **Lambda `procesar`** (contenedor ECR): idempotencia condicional, features, capa 1 reglas (SSM), capa 2 z-score EWMA propio y de cohorte, capa 3 IsolationForest, health score, severidad y top-3 factores. Escribe `Machines`, `MachineState`, `Anomalies`. `ReportBatchItemFailures` | Emite **`AnomalyDetected`** (`contratos.md` §3) **solo si no hay incidente abierto** | RF-02, RF-09, RNF-07 | **Must** |
| A4 | **Lambda `ia-gemini`** (fuera de la VPC): `diagnose`, `summarize_by_role`, `common_cause`, `summarize_chat` y `assistant_chat` con tool-calling. **Fallback determinista** si Gemini falla | Invocada por la SFN de B (payload en §4.2) y por `POST /v1/assistant/chat` | RF-02.6, RF-12.3, RF-14, RF-16.8 | **Must** (diagnose, summarize_chat) / Should (assistant) |
| A5 | **Lambda `heartbeat`** + Scheduler cada 5 min | Emite **`MachineSilent`** | OBS-09 | Should |
| A6 | Firehose → S3 lake (Parquet, particionado) + Glue + Athena workgroup | — | RF-01.4, RNF-05/14 | Should |
| A7 | **SFN `AnalisisDiario`** (Parallel de 4 ramas: preventivo, repuestos, combustible, productividad). Escribe los resultados que expone `api-lectura` | Respuestas de `/v1/maintenance/plan`, `/parts/*`, `/analytics/*` (shape en OpenAPI) | RF-03, RF-04, RF-07, RF-08 | Should |
| A8 | **SFN `Reentrenamiento`** + modelo versionado en S3 + `/model/active_version` en SSM | `GET /v1/ml/model` | RF-13.2, MH-AI-04 | Could |
| A9 | Historial sintético de 3-6 meses con fallas etiquetadas (entrena el IsolationForest) | — | §5.6 | Must (mínimo 1 mes) |

### 1.2 Cómo trabaja sin depender de nadie
- Valida `procesar` con un **SQS local o moto** y verifica sus eventos con una regla de EventBridge `AnomalyDetected → CloudWatch Logs` (no necesita la SFN de B).
- Entrega `ia-gemini` con un **test de invocación directa** (`aws lambda invoke` con los fixtures de `contracts/fixtures/ia/*.json`).

---

## 2. Persona B: Orquestación de incidentes (Step Functions y comandos)

**Misión:** automatizar el ciclo de vida del incidente de punta a punta. Es dueña de la "columna vertebral" y de la plataforma base.

### 2.1 Responsabilidades

| # | Entregable | Contrato que respeta | RF / RNF | Prioridad |
|---|---|---|---|---|
| B0 | **Plataforma base (Hito 0)**: esqueleto Terraform (`infra/base`), tablas DynamoDB (§2.6 de arquitectura, con PITR y Streams), bus `fleet-events`, API Gateway con el Cognito authorizer, Cognito User Pool con los 6 grupos y usuarios demo, topics SNS, secretos vacíos | Naming de §6.3 | RNF-08, RNF-10 | **Must, primero** |
| B1 | Librería **`shared/`** (Python): envoltorio `{data, meta}` / `{error, correlation_id}`, códigos de error, `correlation_id`, logger/tracer/metrics de Powertools, helpers de claves DynamoDB, RBAC por grupo y zona | `contratos.md` §1 | RNF-09, TRZ | **Must, primero** |
| B2 | **SFN `GestionIncidente`** (Standard): `CrearIncidente` condicional → `Parallel` (diagnóstico IA / correlación / stock) → `Choice` severidad → scoring → `Map` notificaciones → canal Firestore → **`EsperarAceptacion`** (`ack_token`, timeout + escalamiento ×2) → **`EsperarResolucion`** (`resolve_token`) → cierre con resumen IA, MTTR, descuento de inventario y `MaintenanceRecord`. Emite `IncidentStateChanged` en cada transición | `AnomalyDetected`, `MachineSilent`, `IncidentStateChanged` | RF-06, RF-10, RF-11, RF-12 | **Must** |
| B3 | **Lambda `api-comandos`** (hoy `api-ack`, fuera de la VPC): `ack`, `assign`, `resolve`, `technicians/me/status`, `ml/retrain` (inicia la SFN de A), `bridge/events` → `SendTaskSuccess` | Rutas `POST` del OpenAPI, `409 INCIDENT_STATE_INVALID` | RF-06.4, RF-11.1, RF-16.5 | **Must** |
| B4 | **Lambda `scoring-tecnicos`**: fórmula ponderada (severidad, ETA haversine, especialidad, disponibilidad y carga). Guarda el puntaje de todos los candidatos | Salida en §4.2 | RF-06.2/06.3, TRZ-03 | **Must** |
| B5 | **Lambda `notificar`**: enruta por `NotificationRules` → SNS email + **publica en Pub/Sub** (REST) con dedup TTL | Mensaje Pub/Sub de `contratos.md` §4 | RF-10.1/10.2/10.5 | **Must** |
| B6 | **Cloud Function Gen2** (GCP): (a) Pub/Sub → push FCM; (b) trigger de `incidents/{id}/actions` → `POST /bridge/events` | `contratos.md` §4 y §5 | RF-10.2, RF-16.5 | Should (a) / **Must** (b si la demo usa el móvil) |
| B7 | **Lambda `correlacion-zona`**: ≥3 máquinas en 30 min → incidente padre + `common_cause` (A4) | GSI `zone#date` | RF-12 | Should |
| B8 | **Lambda `auditoria`**: Streams → `AuditEvents` append-only | — | RNF-15, TRZ-02 | Should |
| B9 | Alarmas CloudWatch (DLQ>0, SFN fallida, errores) → SNS `platform-alarms` | — | OBS | Could |

### 2.2 Cómo trabaja sin depender de nadie
- Arranca la SFN con **eventos falsos**: `aws events put-events --entries file://contracts/fixtures/events/anomaly_detected.json`. No necesita `procesar`.
- Mientras A termina `ia-gemini`, usa un **stub** con la misma firma (§4.2) que devuelve un diagnóstico fijo. Al integrar, solo cambia el ARN.

---

## 3. Persona C: Consulta, tiempo real y frontend (carga backend reducida)

**Misión:** exponer los datos al usuario (REST de lectura + Firestore en vivo). Al construir también el frontend, es dueña de la capa de backend que su propio front consume. Así no espera a nadie y valida los contratos de lectura desde el lado del cliente.

### 3.1 Responsabilidades

| # | Entregable | Contrato que respeta | RF / RNF | Prioridad |
|---|---|---|---|---|
| C1 | **Seeds** de datos maestros: `Machines` (posición inicial), `Technicians` (≥10, especialidades), `Catalog` (20-30 componentes), `Inventory` (2-3 almacenes), `NotificationRules`. Script idempotente `scripts/seed.py` | Mismos IDs que `contratos.md` §1 (`EX-023`, `TEC-07`, `WH-01`, `CMP-014`) | §5.6 | **Must, primero** (lo usan A y B) |
| C2 | **Lambda `api-lectura`** (VPC aislada si F0 lo permite): `GET /v1/me`, `/machines`, `/machines/{id}`, `/machines/{id}/telemetry`, `/machines/{id}/timeline`, `/incidents`, `/incidents/{id}`, `/technicians`, `/inventory`. Paginación por cursor + RBAC | GET del OpenAPI | RF-05, RF-11, RF-02.3 | **Must** |
| C3 | GET analíticos: `/parts/ranking`, `/parts/forecast`, `/maintenance/plan`, `/analytics/*`, `/reports/latest`, `/ml/model`. **Lee lo que escribe A7.** Mientras tanto devuelve datos seed con el shape exacto del OpenAPI | GET del OpenAPI | RF-03/04/07/08 | Should |
| C4 | **Proyecto GCP base**: Firestore, service account para AWS (secreto en Secrets Manager), Security Rules por `role`/`zone` | `contratos.md` §5 | MH-MC-01, RNF-08 | **Must** |
| C5 | **Lambda `replicar`**: Streams de `Machines`, `Incidents` y `Technicians` → Firestore, con el mismo esquema que la API | `contratos.md` §5 | RF-05, RF-15.3, MH-HA-03 | **Must** |
| C6 | `POST /v1/auth/firebase-token` (custom token con claims `role` y `zone`). Va en `api-comandos`, pero **lo escribe C** como handler aparte porque lo necesita su front | OpenAPI | RF-16 | **Must** |
| C7 | Frontend: mapa, cola de incidentes, detalle, chat Firestore (offline) y vistas por rol | — | RF-15, RF-16 | (fuera de este documento) |

### 3.2 Cómo trabaja sin depender de nadie
- `api-lectura` funciona sobre los **seeds** desde el minuto 1. El front se conecta a la API real desde el principio, sin mocks del lado del cliente.
- Para probar el tiempo real, edita un ítem de `Machines` a mano en la consola: el Stream dispara `replicar` → Firestore → el mapa se mueve.

---

## 4. Interfaces entre personas (los "puntos de contacto")

Fuera de estos puntos, nadie toca el código de otro. Cada interfaz tiene **un dueño** (quien la publica) y su **fixture** en `contracts/fixtures/`.

### 4.1 Mapa de dependencias

```
            ┌─────────── C1 seeds (Machines, Technicians, Inventory, Rules) ───────────┐
            ▼                                    ▼                                  ▼
A: procesar ──AnomalyDetected / MachineSilent──► B: GestionIncidente ──invoke──► A: ia-gemini
     │                                              │   │                            ▲
     │ escribe Machines/MachineState/Anomalies      │   └──Pub/Sub──► B: Cloud Function ──FCM
     ▼                                              ▼                         │
  DynamoDB ◄──────────── escribe Incidents/Technicians ──────────────  /bridge/events (B)
     │ Streams                                                                ▲
     ▼                                                                        │
C: replicar ──► Firestore ──► Front (C) ──► actions/{id} ─────────────────────┘
C: api-lectura ◄── GET ── Front (C)          Front ──POST ack/resolve──► B: api-comandos
```

### 4.2 Contratos internos que faltan en `contratos.md` (cerrar en el Hito 0)

`contratos.md` cubre REST, eventos, Pub/Sub y Firestore. Faltan las **invocaciones Lambda internas**. Propuesta (agregar como §8 de `contratos.md`):

| Interfaz | Dueño | Input | Output |
|---|---|---|---|
| `ia-gemini` | A | `{ "task": "diagnose"\|"summarize_by_role"\|"common_cause"\|"summarize_chat"\|"assistant_chat", "correlation_id", "payload": {...} }` | `{ "result": {...}, "model": "gemini-x"\|"fallback", "latency_ms" }`. `diagnose.result` = `{ probable_cause, suggested_action, confidence, parts_suggested[] }` |
| `scoring-tecnicos` | B | `{ incident_id, machine_id, zone, severity, location, required_specialty }` | `{ selected: tech_id, candidates: [{ tech_id, score, eta_min, breakdown{} }] }` |
| `correlacion-zona` | B | `{ incident_id, zone, reading_ts }` | `{ parent_incident_id?, machines[] }` |
| Ítem `Incidents#META` | B escribe, C lee | Mismo shape que el schema `Incident` del OpenAPI + campos internos `ack_token`, `resolve_token`, `execution_arn` | **`api-lectura` y `replicar` nunca exponen los tokens** |
| Ítem `Machines#META` | A escribe status/health, C hace el seed, A7 escribe `next_maintenance` | Shape del schema `Machine` | — |

### 4.3 Decisiones abiertas de `contratos.md` §7 (resolver en el Hito 0, dueño: B)
1. Renombrar `api-ack` → **`api-comandos`** en el OpenAPI (`x-lambda`), el diagrama y este documento.
2. Confirmar **dos task tokens** (`ack_token`, `resolve_token`) en `Incidents`.
3. Quitar `WS /live` de `requerimientos.md` §5.5.
4. Probar si `LabRole` permite Lambda en VPC. Si no, todo fuera de la VPC (afecta a C2).

---

## 5. Plan por hitos

| Hito | Persona A | Persona B | Persona C | Criterio de salida |
|---|---|---|---|---|
| **H0: Base** (primeras ~2 h) | Repo de la imagen ECR + esqueleto de `procesar` | **Terraform base + `shared/` + Cognito + API GW desplegados**. Cerrar §4.3 | Seeds + proyecto GCP + Firestore | `GET /v1/me` responde con JWT; tablas con datos seed |
| **H1: Piezas aisladas** | Simulador + `procesar` (reglas + z-score) emitiendo `AnomalyDetected` | SFN con stubs: crear → scoring → notificar SNS → `ack` → `resolve` | `api-lectura` (Must) + `replicar` + firebase-token | Cada persona demuestra su pieza con fixtures |
| **H2: Golden path E2E** | IsolationForest + `ia-gemini` real (diagnose, summarize_chat) | Pub/Sub → Cloud Function → FCM; bridge desde Firestore | Front: mapa, cola y chat en vivo | **Simulador → incidente cerrado visible en el front, sin intervención manual en la consola** |
| **H3: Cobertura** | `AnalisisDiario` + heartbeat + lake/Athena | `correlacion-zona` (incidente grupal) + `auditoria` + escalamiento por timeout | GET analíticos con datos reales de A7 | Escenarios 3, 4 y 5 del simulador demostrables |
| **H4: Pulido** | `Reentrenamiento` (Could), assistant chat | Alarmas, X-Ray | Vistas por rol, KPIs | Ensayo del pitch 2 veces con datos frescos |

> **Regla:** nadie empieza H3 hasta que el golden path (H2) funcione. Si alguien termina antes, ayuda a destrabar H2 (pairing), no adelanta features.

---

## 6. Buenas prácticas

### 6.1 Estructura del repo (monorepo)

```
contracts/            openapi.yaml, contratos.md, events/*.schema.json, fixtures/{events,ia,api}/
infra/
  base/               (B) tablas, bus, API GW, Cognito, SNS, secretos
  ingest/             (A) SQS, procesar, Firehose, Glue, Athena, SFN AnalisisDiario/Reentrenamiento
  incidents/          (B) SFN GestionIncidente, lambdas de incidente, reglas EventBridge
  query/              (C) api-lectura, replicar
  gcp/                (C base + B Cloud Function) Firestore, rules, Pub/Sub, CF
services/
  shared/             (B) librería común. Cambios por PR con review de los 3
  ingest/{procesar,heartbeat}/                     (A)
  ai/ia_gemini/                                    (A)
  analytics/{preventivo,repuestos,combustible,productividad,retrain}/  (A)
  incidents/{api_comandos,scoring,correlacion,notificar,auditoria}/    (B)
  incidents/sfn/gestion_incidente.asl.json         (B)
  query/{api_lectura,replicar}/                    (C)
gcp/functions/notify_bridge/                       (B)
simulator/                                         (A)
scripts/              seed.py (C), smoke_golden_path.sh (todos)
frontend/                                          (C)
```

Cada carpeta de servicio tiene `handler.py`, `requirements.txt`, `tests/` y un `README.md` de 5 líneas: qué hace, qué consume, qué produce, cómo probarlo y qué RF cubre.

### 6.2 Contract-first
- **El contrato manda.** Si necesitas cambiar un endpoint, un evento o un campo: (1) PR a `contracts/`, (2) aprobación de quien consume esa interfaz, (3) recién entonces el código. Así lo dice `contratos.md`.
- Todo evento o payload interno tiene un **fixture JSON** en `contracts/fixtures/`. Los tests de productor y consumidor usan **el mismo fixture**.
- Valida las respuestas de `api-lectura`/`api-comandos` contra `openapi.yaml` en los tests (`openapi-core`), o al menos con un test de shape.
- Campos nuevos: solo **aditivos** (opcionales). Nunca renombrar ni quitar campos sin subir `version` del evento.

### 6.3 Convenciones de código y nombres
- **Lenguaje:** Python 3.12 en todas las Lambdas (es lo que exige `procesar` con sklearn). La Cloud Function también en Python.
- **Recursos AWS:** `arquifusion-{stage}-{nombre}` (p. ej. `arquifusion-dev-procesar`). Tags: `project=arquifusion`, `owner=A|B|C`, `rf=RF-xx`.
- **Handlers delgados:** `handler.py` solo parsea, valida y llama a `service.py`. La lógica de negocio va en funciones puras, testeables sin AWS.
- Usa **siempre** `shared/` para respuestas, errores, logger y RBAC. Prohibido armar `{"error": ...}` a mano.
- Clientes boto3 y configuración **fuera del handler** (se reusan entre invocaciones). Secretos con Powertools Parameters, con caché de 5 min.

### 6.4 Confiabilidad
- **Idempotencia** en todo consumidor: escrituras condicionales en DynamoDB (`attribute_not_exists`, `status = :expected`). Un `ack` repetido → `409`, no un doble `SendTaskSuccess`.
- **`correlation_id` de punta a punta:** se lee del header o del evento, se loggea y se propaga a EventBridge, Pub/Sub, Firestore y la SFN. Si un flujo pierde el id, es un bug.
- **Timeouts y fallback** en toda llamada a GCP: Gemini con timeout ≤ 8 s y respuesta determinista si falla. Nunca bloquear la SFN por la IA.
- En la SFN: `Retry` con backoff en cada Task, `Catch` hacia un estado de error que marque el incidente y notifique. Nada de fallos silenciosos.
- SQS: `ReportBatchItemFailures` (no reintentar el lote entero).

### 6.5 Seguridad
- Cero secretos en código, `.env` commiteados, variables de entorno o frontend. Todo va en Secrets Manager / SSM. `.gitignore` con `*.tfstate`, `.env*` y `*credentials*`.
- RBAC **dentro** de la Lambda además del authorizer: el técnico solo hace `ack`/`resolve` de **sus** incidentes; `gerencia` solo hace GET.
- Firestore Rules con los claims `role`/`zone`. Probarlas con el emulador antes de la demo.
- No exponer `ack_token`/`resolve_token` en ninguna respuesta ni réplica.

### 6.6 Observabilidad
- Logs JSON (Powertools Logger) con `correlation_id`, `machine_id` e `incident_id` como claves estándar.
- Métricas EMF por servicio y severidad. **Nunca** `machine_id` como dimensión (costo).
- X-Ray activo en las Lambdas fuera de la VPC y en las SFN.

### 6.7 Git y colaboración
- Rama `main` siempre desplegable. Ramas `feat/<persona>-RF-xx-descripcion` (p. ej. `feat/b-RF-06-scoring`).
- Commits convencionales **con el ID de requerimiento**: `feat(incidents): scoring de técnicos por ETA (RF-06.2)`.
- PRs pequeños (< 300 líneas) con review de 1 persona. Si tocan `contracts/` o `shared/`, review de las 3.
- **Sync de 10 min cada ~3 h:** qué terminé, qué me bloquea y qué contrato necesito cambiar.

### 6.8 Entornos en AWS Academy
- Cada Learner Lab es **una cuenta distinta** y las credenciales caducan (~4 h). Por eso:
  - **Cuenta de integración única** (la de B): ahí vive `stage=dev` y se hace la demo. Desplegar ahí solo desde `main`.
  - Cada persona prueba en **su propio lab** con `stage=<inicial>` antes de hacer merge.
- Terraform: **un state por carpeta de `infra/`** (key distinta en S3, `use_lockfile`). Así A, B y C no se bloquean el lock entre sí. Las salidas compartidas (ARN del bus, nombres de tabla) se leen con `terraform_remote_state` o desde SSM.
- Todo recurso se crea por Terraform. Si algo se hizo a mano en la consola para probar, se borra o se codifica antes del merge.

### 6.9 Pruebas y Definition of Done
- **Unit:** `pytest` sobre `service.py` (funciones puras). Para DynamoDB, `moto`.
- **Contrato:** productor y consumidor prueban contra el mismo fixture.
- **Smoke E2E:** `scripts/smoke_golden_path.sh` lanza el escenario de degradación, espera el incidente, hace `ack` y `resolve` y verifica `closed` + resumen IA. **Se corre antes de cada merge a `main` desde H2.**

Una tarea está **terminada** cuando:
1. Está desplegada por IaC en la cuenta de integración.
2. Respeta el contrato (fixture/test en verde).
3. Loggea con `correlation_id` y maneja sus errores con el envoltorio estándar.
4. Tiene su README de 5 líneas con el RF que cubre.
5. El smoke del golden path sigue pasando.
