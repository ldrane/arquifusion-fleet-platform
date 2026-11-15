# ArquiFusion Corp — Arquitectura de Solución en AWS

> Base: `requerimientos.md` (RF/RNF) + `analisis-brechas-plan-aws-academy.md` (MH-*).
> Entorno: AWS Academy Learner Lab · región **us-east-1** · rol único **`LabRole`** · segunda nube: **GCP**.
> Restricciones aplicadas: sin creación de roles IAM, sin NAT Gateway, sin servicios con costo por hora, sin EC2/RDS/contenedores encendidos.

---

## 1. Diagrama de arquitectura

### 1.1 Vista general (Mermaid)

```mermaid
flowchart LR
  %% ===================== CLIENTES =====================
  subgraph CLIENTES["Clientes"]
    SIM["Simulador de flota<br/>(Python, local)"]
    WEB["App web / móvil<br/>(React + Leaflet)"]
  end

  %% ===================== BORDE =====================
  subgraph EDGE["Capa de borde (AWS administrado)"]
    COG["Cognito<br/>User Pool + grupos"]
    APIGW["API Gateway REST<br/>/telemetry (API key)<br/>/v1/* (Cognito JWT)"]
  end
  %% El front se sirve con Firebase Hosting (GCP). CloudFront + S3 (OAC) es la alternativa fuera del Learner Lab.

  %% ===================== INGESTA =====================
  subgraph INGESTA["Ingesta (hot path)"]
    SQS["SQS ingest"]
    DLQ["SQS DLQ"]
    LPROC["Lambda procesar<br/>(container ECR)<br/>reglas + z-score + IsolationForest"]
  end

  %% ===================== DATOS =====================
  subgraph DATOS["Capa de datos"]
    DDB[("DynamoDB on-demand<br/>PITR + Streams")]
    FH["Kinesis Firehose<br/>→ Parquet"]
    S3L[("S3 data lake<br/>versionado + lifecycle")]
    GLUE["Glue Data Catalog"]
    ATH["Athena"]
    S3M[("S3 modelos ML<br/>versionado")]
  end

  %% ===================== ORQUESTACIÓN =====================
  subgraph ORQ["Orquestación"]
    EB["EventBridge<br/>bus fleet-events"]
    SCH["EventBridge Scheduler"]
    SFN1["SFN GestionIncidente<br/>(Standard)"]
    SFN2["SFN AnalisisDiario<br/>(Standard)"]
    SFN3["SFN Reentrenamiento<br/>(Standard)"]
  end

  %% ===================== SERVICIOS =====================
  subgraph SVC["Lambdas de dominio"]
    LAPI["Lambdas API<br/>(lectura/escritura)"]
    LASSIGN["Lambda scoring técnicos"]
    LCORR["Lambda correlación zona"]
    LNOTIF["Lambda notificar por rol"]
    LTG["Lambda notify-telegram"]
    LNPUSH["Lambda notify-push<br/>(FCM HTTP v1)"]
    LREPL["Lambda replicar<br/>(Streams → Firestore)"]
    LAI["Lambda IA<br/>(cadena Gemini → Bedrock → determinista)"]
    LHB["Lambda heartbeat"]
    LSIM["Lambda sim-driver<br/>(gemelo de flota)"]
    LEXP["Lambda export-gcp<br/>(DR → BigQuery)"]
    LAUD["Lambda auditoria<br/>(VPC aislada)"]
  end
  %% TAREA-16: solo `auditoria` corre dentro de la VPC aislada (2 subredes privadas + Gateway Endpoint DynamoDB).
  %% El resto sale a Internet / otros servicios (GCP, Athena, Secrets Manager, SFN) y la VPC no tiene NAT.

  %% ===================== TRANSVERSAL =====================
  subgraph TRANS["Transversal"]
    SM["Secrets Manager"]
    SSM["SSM Parameter Store"]
    CW["CloudWatch Logs/Metrics<br/>Dashboards/Alarms"]
    XR["X-Ray"]
    SNS["SNS topics por rol"]
  end

  %% ===================== GCP =====================
  subgraph GCP["Google Cloud"]
    GEM["Gemini API<br/>(AI Studio / Vertex express)"]
    FS[("Firestore<br/>chat + réplica")]
    PS["Pub/Sub<br/>(opcional: Cloud Functions)"]
    FCM["Firebase Cloud Messaging"]
    BQ[("BigQuery (sandbox)<br/>réplica DR diaria")]
    LK["Looker Studio<br/>(Gerencia)"]
    FBH["Firebase Hosting<br/>(front)"]
    TG["Telegram Bot API<br/>(alertas + decisiones)"]
  end

  SIM -->|HTTPS + x-api-key| APIGW
  WEB --> FBH
  WEB -->|login| COG
  WEB -->|HTTPS + JWT| APIGW
  WEB <-->|listeners tiempo real| FS

  APIGW -->|integración directa| SQS
  APIGW --> LAPI
  SQS --> LPROC
  SQS -.->|3 fallos| DLQ
  LPROC --> DDB
  LPROC --> FH --> S3L
  LPROC -->|AnomalyDetected| EB
  S3M -.->|carga en init| LPROC

  EB --> SFN1
  EB --> LTG
  EB --> LAUD
  SFN1 --> LAI --> GEM
  SFN1 --> LCORR
  SFN1 --> LASSIGN
  SFN1 --> LNOTIF
  SFN1 --> DDB
  LNOTIF --> SNS
  LNOTIF --> PS
  LNOTIF --> LNPUSH --> FCM
  LTG --> TG
  TG -->|webhook (botones)| APIGW
  LNPUSH -->|ack técnico / comandos| APIGW
  LSIM -->|telemetría simulada| APIGW

  SCH --> SFN2
  SCH --> SFN3
  SCH --> LHB
  SCH --> LSIM
  SFN2 --> ATH
  SFN3 --> ATH
  SFN3 --> S3M
  ATH --> GLUE
  ATH --> S3L

  DDB -->|Streams| LREPL --> FS
  SFN2 --> LEXP --> BQ --> LK

  LAPI --> DDB
  LAUD --> DDB
  SM -.-> LAI
  SM -.-> LREPL
  SM -.-> LNOTIF
  SM -.-> LTG
  SM -.-> LEXP
  SSM -.-> LPROC
  LPROC -.-> CW
  SFN1 -.-> XR
```

### 1.2 Vista por capas (ASCII)

```
┌──────────────────────────────────────────── CLIENTES ─────────────────────────────────────────────┐
│  Simulador (local)                          Web/Móvil (operador, técnico, mantenimiento, gerencia) │
└───────┬──────────────────────────────────────────────┬─────────────────────────┬───────────────────┘
        │ HTTPS + API key                              │ HTTPS + JWT             │ SDK Firestore (WSS)
┌───────▼──────────────────────── BORDE (sin VPC, administrado) ─────────────────▼───────────────────┐
│  API Gateway REST  ── Cognito authorizer ──  (front servido por Firebase Hosting, GCP)             │
└───────┬──────────────────────────────┬─────────────────────────────────────────────────────────┘
        │ /telemetry                   │ /v1/*
┌───────▼──────────── INGESTA ─────────▼─────────────── VPC aislada `auditoria` ──────────────────────┐
│  SQS ingest ─► Lambda procesar      │ Lambda auditoria ─► Gateway Endpoint DynamoDB                 │
│      └─► DLQ    (ECR container)     │   (subred privada, sin internet; solo DynamoDB)               │
└───────┬─────────────────────────────┴───────────────────────────────────────────────────────────┘
        │                                                                        
┌───────▼────────────────────────────── DATOS ───────────────────────────────────────────────────────┐
│  DynamoDB (PITR, Streams) │ Firehose ─► S3 lake (Parquet) ─► Glue ─► Athena                        │
└───────┬──────────────────────────────────────────────────────────────────┬─────────────────────────────┘
        │ AnomalyDetected                                     Streams      │
┌───────▼──────────────── ORQUESTACIÓN ───────────────────┐   ┌────────────▼───────────────── GCP ────┐
│  EventBridge ─► SFN GestionIncidente                     │   │  Firestore (chat, réplica, realtime) │
│  Scheduler   ─► SFN AnalisisDiario / Reentrenamiento     │◄─►│  Gemini API · FCM · Firebase Hosting │
│              ─► Lambda heartbeat / sim-driver            │   │  BigQuery (DR) · Looker · Telegram   │
└──────────────────────────────────────────────────────────┘   └──────────────────────────────────────┘
  Transversal: Secrets Manager · SSM · CloudWatch · X-Ray · SNS · LabRole · KMS (claves AWS-managed)
```

---

## 2. Stack tecnológico y justificación

### 2.1 Borde y acceso

| Servicio | Configuración | Problema que resuelve | Cubre |
|---|---|---|---|
| **Firebase Hosting (GCP)** | Sitio estático (`frontend/firebase.json`), HTTPS administrado, CDN global, sin costo | Sirve el frontend con TLS sin bucket público | RF-15, RNF-08, MH-SEC-05 |
| **CloudFront + S3 (opcional)** | Alternativa fuera del Learner Lab: distribución CloudFront con origen S3 vía **OAC**, bucket privado | Hosting estático alternativo (el Learner Lab deniega CloudFront) | RF-15, RNF-02 |
| **Amazon Cognito User Pool** | Grupos: `operador`, `tecnico`, `mantenimiento`, `supervisor`, `admin`, `gerencia`. Sin Identity Pool (requiere crear roles) | Autenticación y RBAC por rol | RNF-08, RF-15.1, MH-SEC-02 |
| **Amazon API Gateway (REST)** | Un solo API con dos zonas: `/telemetry` (API key + usage plan + *request validator* JSON Schema + integración directa a SQS usando `LabRole`) y `/v1/*` (Cognito authorizer → Lambdas). Throttling por etapa. | Punto único de entrada, validación previa y protección contra abuso | RF-01.1/01.3, §5.5 APIs, MH-SEC-06, MH-NET-02 |

### 2.2 Ingesta y procesamiento (hot path)

| Servicio | Configuración | Problema que resuelve | Cubre |
|---|---|---|---|
| **Amazon SQS (ingest + DLQ)** | Standard, visibilidad de 60 s, `maxReceiveCount=3` → DLQ, retención de 4 días | Desacopla la ingesta del cómputo, absorbe picos y no pierde mensajes. Pago por request, $0 en reposo | RF-01.3/01.4, RNF-07, ESC-04, MH-HA-05, corrección C4 |
| **AWS Lambda `procesar`** | **Imagen de contenedor (ECR)** Python 3.12 + numpy/sklearn, 1024 MB, batch 100, ventana de 5 s, `ReportBatchItemFailures`, `MaximumConcurrency` acotado | Normaliza lecturas, aplica reglas, z-score (baseline propio y de cohorte) e IsolationForest. Calcula health score, guarda estado y agregados y emite eventos | RF-02.1–02.4, RF-09, ESC-03/07, MH-AI-01/02/03 |
| **Amazon ECR** | Repositorio privado, scan on push, lifecycle de 5 imágenes | Empaqueta dependencias ML que exceden el límite de 250 MB de una Lambda en zip | MH-AI-01, W-13 |
| **Amazon EventBridge (bus `fleet-events`)** | Reglas por `detail-type` (`AnomalyDetected`, `MachineSilent`, `IncidentResolved`) | Desacopla la detección de la respuesta: un evento, múltiples consumidores | ESC-04, RNF-11 |

### 2.3 Capa de datos

| Servicio | Configuración | Problema que resuelve | Cubre |
|---|---|---|---|
| **Amazon DynamoDB** | On-demand, **PITR ON**, **Streams `NEW_AND_OLD_IMAGES`**, cifrado AWS-owned, TTL en tablas temporales. Tablas en §2.6 | Estado operacional de baja latencia y escalado automático; base del event sourcing | RF-05, RF-06, RF-11, RNF-05, ESC-02, MH-HA-02 |
| **Amazon Data Firehose** | Direct PUT desde Lambda, conversión a **Parquet** con esquema Glue, buffer de 5 min / 64 MB, prefijo `operation_id=/dt=/machine_type=` (dynamic partitioning) | Lleva la telemetría cruda al data lake sin servidores ni código de batching | RF-01.4, ESC-05/08, MH-HA-01 |
| **Amazon S3 (data lake)** | Versionado ON, lifecycle Standard → Standard-IA (30 d) → Glacier Flexible (90 d) → expiración a 400 d, SSE-S3 | Durabilidad de 11 nueves y retención barata ≥ 1 año | RNF-05, RNF-14, RNF-03 |
| **S3 (modelos y artefactos)** | Bucket separado, versionado, `models/isolation_forest/vN/model.joblib` | Versionado de modelos ML | TRZ-05, RF-13.2 |
| **AWS Glue Data Catalog** | Base `arquifusion`, tablas `telemetry_raw`, `incidents_export`. Sin crawlers (tablas definidas en IaC) | Esquema para Firehose (Parquet) y Athena | ESC-08 |
| **Amazon Athena** | Workgroup con bucket de resultados y límite de bytes escaneados por consulta | Analítica SQL serverless sobre el histórico (combustible, productividad, patrones precursores, entrenamiento) | RF-07, RF-08, RF-13, ESC-05 |

### 2.4 Orquestación

| Servicio | Configuración | Problema que resuelve | Cubre |
|---|---|---|---|
| **AWS Step Functions — `GestionIncidente`** | **Standard**, `LabRole`, X-Ray ON. Patrones: `Parallel`, `Choice`, `Map`, `.waitForTaskToken` + `TimeoutSeconds`, `Retry`/`Catch`, integraciones SDK directas a DynamoDB | Automatiza el ciclo completo del incidente con esperas humanas y escalamiento | RF-06, RF-10, RF-11.1, RF-12, MH-SFN-01 |
| **Step Functions — `AnalisisDiario`** | Standard, `Parallel` con 4 ramas | Plan preventivo, pronóstico de repuestos, combustible y productividad | RF-03, RF-04, RF-07, RF-08, MH-SFN-02 |
| **Step Functions — `Reentrenamiento`** | Standard, semanal + manual, `Choice` de promoción | Pipeline ML automatizado y versionado | RF-13.2, TRZ-05, MH-SFN-03 |
| **EventBridge Scheduler** | `LabRole` como rol de ejecución. Crons: diario 05:00 Lima, semanal domingo, heartbeat cada 5 min | Disparadores programados sin servidores | RF-03.3, RF-13, OBS-09 |

### 2.5 Lambdas de dominio, notificación y transversales

| Servicio | Función | Cubre |
|---|---|---|
| **Lambda `scoring-tecnicos`** | Puntaje = `w1·severidad + w2·(1/ETA haversine) + w3·match_especialidad + w4·disponibilidad − w5·carga_actual`. Guarda el puntaje de todos los candidatos | RF-06.2/06.3, RF-05.3, TRZ-03 |
| **Lambda `correlacion-zona`** | Consulta el GSI `zone#date` de anomalías en una ventana de 30 min. Si hay ≥ 3 máquinas en la zona, crea un incidente padre | RF-12.1/12.2 |
| **Lambda `ia-gemini`** | Cadena de proveedores LLM (Gemini API vía AI Studio o Vertex express → Bedrock → motor determinista) con credencial desde Secrets Manager. Diagnóstico, resumen por rol, causa común, resumen del chat al cierre y tool-calling del asistente. Registra `provider` y `degraded` en el diagnóstico | RF-02.6, RF-07.4, RF-10.3, RF-12.3, RF-14, RF-16.8, MH-MC-03 |
| **Lambda `notificar`** | Enruta por la tabla `NotificationRule` (rol × severidad × tipo). Canales: SNS (email), webhook (Slack/Discord), Pub/Sub → FCM y Telegram. Dedup con TTL | RF-10.1/10.2/10.5 |
| **Lambda `notify-push`** | Envía push FCM HTTP v1 al técnico/operador asignado (token registrado en `/auth/firebase-token`) | RF-10.2, RF-16.5 |
| **Lambda `notify-telegram`** | Bot de Telegram: alerta con botones inline (`ack:<id>:accept|reject`) y comandos; webhook entrante en `/telegram/webhook` (secret token) | RF-10.2, RF-16.5 |
| **Lambda `replicar`** | DynamoDB Streams → Firestore (máquinas, incidentes, técnicos) | MH-HA-03, MH-MC-01 |
| **Lambda `auditoria`** | Consume el bus `fleet-events` → tablas `audit-events` (append-only) y el historial `EVT#` en `incidents` (antes/después, actor, motivo). Corre en la **VPC aislada** (TAREA-16) | RNF-15, TRZ-02/06 |
| **Lambda `heartbeat`** | Marca `SILENT` las máquinas sin lectura en más de 3× su frecuencia → evento `MachineSilent` | OBS-09 |
| **Lambda `sim-driver`** | Gemelo de flota serverless: EventBridge Scheduler la invoca cada minuto y emite telemetría simulada contra `/telemetry` mientras el estado en SSM esté encendido | RF-01, TAREA-07 |
| **Lambda `export-gcp`** | Exporta el lake diario, incidentes cerrados e insights a BigQuery (DR multinube, §2.8) | RNF-04/05 |
| **Lambdas API** (`/v1/*`) | CRUD de lectura (`api-lectura`) y acciones (`api-comandos`: `ack`, `assign`, `resolve`). `ack` llama a `SendTaskSuccess` | §5.5, RF-06.4, TRZ-09 |
| **Amazon SNS** | Topics por rol (`alerts-tecnico`, `alerts-mantenimiento`, `alerts-gerencia`) + topic `platform-alarms` | RF-10.2, MH-OBS-03 |
| **AWS Secrets Manager** | `gcp/service-account`, `gemini/api-key`, `webhook/slack`, `simulator/api-key`, `bridge/gcp-api-key` | Rúbrica (variables globales), MH-SEC-03 |
| **SSM Parameter Store** | `/arquifusion/{stage}/thresholds/*`, `/model/active_version`, `/prompts/version` (String/SecureString estándar, gratis) | RF-02.1, TRZ-05 |
| **Amazon CloudWatch** | Logs JSON (Powertools), retención de 7 días, métricas EMF sin `machine_id` como dimensión, 2 dashboards, alarmas → SNS | RNF-09, OBS-01–07, MH-OBS |
| **AWS X-Ray** | Tracing activo en Lambda, API Gateway y Step Functions | OBS-02, MH-OBS-07 |
| **KMS (claves AWS-managed)** | `aws/s3`, `aws/sqs`, `aws/secretsmanager`. DynamoDB con su clave propia | RNF-08, MH-SEC-04 |
| **IAM `LabRole`** | Único rol de ejecución en todo el stack | W-01, MH-IAC-03 |
| **Terraform** (providers `aws` + `google`) | Estado en S3 con `use_lockfile` | RNF-10, MH-IAC-02 |

### 2.6 Modelo de datos en DynamoDB

Tablas físicas `{prefix}-<nombre>` (`infra/base/main.tf`); todas on-demand, PITR ON y Streams `NEW_AND_OLD_IMAGES`. Los `pk`/`sk` llevan prefijos/entidades por convención (§9.1 de `contratos.md`).

| Tabla | PK | SK | GSI | Notas |
|---|---|---|---|---|
| `machines` | `operation_id#machine_id` | `META` | `by_zone: zone → machine_id` | Estado, health score, próximo mantenimiento, `last_seen_at` |
| `machine-state` | `machine_id` | `AGG#1h#...` / `BASELINE` / `LAST` | — | Agregados 1 min/1 h/1 d, baseline EWMA y última lectura (ESC-07). TTL `expires_at` |
| `idempotency` | `machine_id#timestamp` | — | — | Escritura condicional, TTL 24 h (RNF-07) |
| `anomalies` | `machine_id` | `ts#anomaly_id` | `by_zone: zone → detected_at` | Variables, score, `model_version`, tipo (individual/cohorte/tendencia) |
| `incidents` | `INC#incident_id` | `META` / `EVT#ts#event_id` | `by_machine: machine_id → detected_at`, `by_status: status → detected_at` | Incluye `ai_diagnosis`, `parent_incident_id`, `correlation_id`; los `EVT#` son el historial (no salen en listas) |
| `technicians` | `TEC#technician_id` | `META` | `by_zone: zone → technician_id` | Especialidades, ubicación y carga |
| `inventory` | `location_id` | `component_id` | `by_component: component_id → warehouse_id` | Stock, mín. y máx. |
| `catalog` | `component_id` / `model_id` | `COMPAT#...` | — | Componentes y compatibilidades |
| `warehouses` | `warehouse_id` | `META` | — | Almacenes del seed (#19) |
| `notification-rules` | `role` | `severity#event_type` | — | Canales y plantilla |
| `audit-events` | `incident#<id>` / `machine#<id>` | `ts#event_id` | — | Append-only (`attribute_not_exists(pk)`), sin secretos (F-14) |
| `maintenance-records` | `ASSET#machine_id` | `REC#<ts>` | — | Preventivo/correctivo; lo escribe B al cerrar |
| `insights` | `ml_model` / `report#daily` / `kpis#...` | `LATEST` | — | Salidas del workflow analítico (los escribe A, los lee C) |

### 2.7 Componentes en GCP (rol real, no decorativo)

| Servicio GCP | Rol | Cubre |
|---|---|---|
| **Gemini API (AI Studio / Vertex express)** | LLM de diagnóstico, resúmenes y asistente con function calling (primer proveedor de la cadena `gemini → bedrock → determinista`) | RF-02.6, RF-14, RF-16.8 |
| **Firestore** | Canales de incidente (chat), estado en tiempo real del mapa, **persistencia offline** en el móvil y réplica de entidades críticas | RF-05, RF-15.3, RF-16, MH-HA-03 |
| **Firebase Cloud Messaging** | Push al móvil del técnico u operador (HTTP v1 desde `notify-push`) | RF-10.2 |
| **Firebase Hosting** | Sirve el front React compilado (HTTPS, CDN, sin costo) | RF-15, RNF-08 |
| **BigQuery (sandbox)** | Réplica DR diaria del lake, incidentes cerrados e insights (`export-gcp`) | RNF-04/05 |
| **Looker Studio** | Tablero de Gerencia sobre BigQuery (enlace en `VITE_LOOKER_URL`) | RF-07, RF-15 |
| **Telegram Bot API** | Alertas con botones de decisión y comandos (`notify-telegram`, webhook `/telegram/webhook`) | RF-10.2, RF-16.5 |

### 2.8 Recuperación ante desastres (DR multinube)

Si AWS pierde el *data lake* o la base de incidentes, el historial sigue disponible en otra nube y otra región:

| Qué | Réplica | RPO | RTO |
|---|---|---|---|
| Lake diario (`daily_machine_stats`), incidentes cerrados e insights `kpis#*` | **BigQuery (sandbox)** vía Lambda `export-gcp` al final de `AnalisisDiario` (load jobs por lotes; el sandbox no permite streaming) | 24 h | minutos (consultar/restaurar desde el dataset) |
| Estado operativo (máquinas, incidentes abiertos, técnicos) | **Firestore** vía DynamoDB Streams (`replicar`) | ≈ segundos | segundos (el front ya lee Firestore) |

- La Lambda `export-gcp` (stack `query`) sube a BigQuery el CSV que dejó Athena en S3, los incidentes con `closed_at` en las últimas 24 h (solo campos públicos) y los KPIs `7d`/`30d`. Es **best-effort**: un fallo de GCP queda en el resultado del estado `ExportarGCP` sin tumbar el análisis diario.
- El dataset (`arquifusion_<stage>`, `infra/gcp/bigquery.tf`) es de solo réplica: `delete_contents_on_destroy = true` porque la fuente de verdad es AWS.
- **Tablero de Gerencia (Looker Studio):** 1) crea el reporte en Looker Studio; 2) agrega la fuente de datos **BigQuery** → proyecto de la service account → dataset `arquifusion_<stage>`; 3) gráficos sugeridos: línea de `kpis_daily` (disponibilidad), barras de `daily_machine_stats` por zona y tabla de `incidents`; 4) publica el enlace y pégalo en `VITE_LOOKER_URL` (el botón "Tablero de Gerencia" en *Eficiencia* lo abre).

---

## 3. Diseño de red y seguridad

### 3.1 Principio de diseño

La plataforma es **serverless y sin cómputo expuesto**. El perímetro lo forman servicios administrados por AWS (API Gateway, Cognito), que ya son multi-AZ y con TLS. Por eso:

- **No hay subredes públicas, Internet Gateway ni NAT Gateway.** Un NAT cuesta ~USD 32/mes + datos, consume el presupuesto del lab y no es pago por uso (MH-NET-01).
- Se usa **una VPC aislada (TAREA-16) solo para la Lambda `auditoria`**: escribe el ledger append-only en DynamoDB y no necesita salir a Internet, así que corre en subredes privadas y accede por un **Gateway Endpoint de DynamoDB** (gratis).
- El resto de Lambdas corre **fuera de la VPC** porque salen a Internet o a otros servicios (GCP, Athena, Secrets Manager, Step Functions, SNS). Su seguridad se basa en Cognito/IAM + TLS + secretos gestionados (modelo *zero-trust serverless*).

### 3.2 Topología de la VPC `{prefix}-vpc-audit`

```
VPC {prefix}-vpc-audit  10.20.0.0/16   (us-east-1, DNS hostnames ON, sin IGW, sin NAT)
│
├── Subred privada A   10.20.1.0/24   us-east-1a
├── Subred privada B   10.20.2.0/24   us-east-1b
│      └─ Route table privada:
│           10.20.0.0/16         → local
│           pl-xxxx (DynamoDB)   → vpce-ddb  (Gateway Endpoint)
│           (sin ruta 0.0.0.0/0)
│
└── Gateway Endpoint DynamoDB  (services: com.amazonaws.us-east-1.dynamodb)
```

| Elemento | Decisión |
|---|---|
| **Subredes públicas** | Ninguna. No hay recursos que deban tener IP pública. |
| **Subredes privadas** | 2 subredes aisladas en 2 AZ (alta disponibilidad de las ENI de Lambda). |
| **Interface Endpoints** | No se usan (~USD 7/mes por endpoint por AZ). Por eso solo `auditoria` (que solo habla con DynamoDB) entra en la VPC. |
| **NACL** | Default (stateless allow-all interno). El control fino se hace con el SG. |
| **VPC Flow Logs** | Opcional (`var.vpc_flow_logs`, apagado por defecto): el Learner Lab no permite crear el rol que `aws_flow_log` necesita. Si tu cuenta lo permite, activarlo escribe a CloudWatch Logs (retención 7 días). |

**Lambdas dentro de la VPC:** `auditoria` (única).
**Lambdas fuera de la VPC:** el resto — `api-lectura`, `procesar`, `ia-gemini`, `notificar`, `notify-push`, `notify-telegram`, `replicar`, `scoring-tecnicos`, `correlacion-zona`, `heartbeat`, `export-gcp`, `sim-driver`, `api-comandos` (Step Functions, API Gateway) y las Lambdas de `AnalisisDiario` / `Reentrenamiento` (Athena).

> **Modelo *zero-trust serverless* (resto de la plataforma):** Cognito JWT en API Gateway, API keys (máquinas y puente GCP→AWS), OIDC de Pub/Sub en `/bridge/push`, Telegram secret token en `/telegram/webhook`, y `LabRole` + separación por `stage` (tablas/buckets por nombre). Las políticas de mínimo privilegio por función para producción están en `docs/iam-produccion/`.

### 3.3 Security Groups

| SG | Asociado a | Inbound | Outbound |
|---|---|---|---|
| `{prefix}-sg-lambda-data` | Lambda `auditoria` | **Ninguna regla** (Lambda no recibe tráfico entrante) | TCP 443 → prefix list `com.amazonaws.us-east-1.dynamodb` |

No hay más SG porque no hay otros recursos con ENI (sin EC2, RDS, ALB ni endpoints de interfaz).

### 3.4 Manejo de accesos (capas de seguridad)

| Capa | Mecanismo |
|---|---|
| **Identidad de usuarios** | Cognito User Pool (MFA opcional TOTP, política de contraseñas). Grupos = roles. El JWT incluye `cognito:groups` y `custom:zone`. |
| **Autorización API** | Cognito authorizer en API Gateway + validación de rol y zona dentro de cada Lambda (RBAC). Por ejemplo, `gerencia` solo puede hacer GET y `tecnico` solo puede hacer `ack`/`resolve` de sus incidentes asignados. |
| **Identidad de máquinas** | API key por operación (`simulator-{operation_id}`) + usage plan (rate 500 rps, burst 1.000, cuota diaria). |
| **Puente GCP → AWS** | API key dedicada `bridge-gcp` en un recurso aparte `/bridge/*` con throttling bajo. La key vive en Secret Manager de GCP; su contraparte, en Secrets Manager de AWS. |
| **Identidad de servicios** | `LabRole` en todos los recursos (limitación del lab). Mitigación: endpoint policies en los Gateway Endpoints, bucket policies restrictivas y separación de tablas/buckets por `stage`. Se documentan en `docs/iam-produccion/` las políticas de mínimo privilegio por función para producción. |
| **Secretos** | Secrets Manager (credenciales GCP, API keys, webhooks) leído con caché (Powertools Parameters, TTL 5 min). Configuración en SSM. Nada en variables de entorno, repo ni frontend. |
| **Datos en reposo** | SSE-S3 (buckets), cifrado DynamoDB, SQS SSE (`aws/sqs`), Secrets Manager con `aws/secretsmanager`. |
| **Datos en tránsito** | TLS 1.2+ en Firebase Hosting (HTTPS administrado) y API Gateway. Bucket policies con `aws:SecureTransport = false → Deny`. |
| **Bucket policies** | Lake: deny sin TLS y deny `s3:DeleteObject*` excepto lifecycle (política en `lab_s3_bucket`). Si se usa la alternativa CloudFront+S3: solo el principal `cloudfront.amazonaws.com` con `AWS:SourceArn` de la distribución (OAC). |
| **Firestore** | Security Rules: solo participantes del canal leen y escriben. `admin` y `gerencia` son de solo lectura. Escritura de réplica únicamente por la service account de AWS. |
| **Auditoría** | CloudTrail Event History (90 días) + tabla `AuditEvents` append-only + historial de ejecuciones de Step Functions. |

---

## 4. Flujo de datos paso a paso

### Flujo A — Ingesta de telemetría y detección (hot path, objetivo ≤ 60 s)

1. **Simulador** genera un lote de N lecturas (`machine_id`, `timestamp`, ubicación, variables, `operation_id`) y envía `POST /telemetry` con header `x-api-key`.
2. **API Gateway** valida la API key y el usage plan (throttling) y aplica el **JSON Schema** del *request validator*. Si es inválido → `400` sin costo de cómputo. Genera un `correlation_id` (`$context.requestId`) y lo añade como atributo del mensaje.
3. **Integración directa API Gateway → SQS** (`SendMessage` con `LabRole`) → responde `202 Accepted`.
4. **SQS** dispara la **Lambda `procesar`** en lotes de hasta 100 mensajes (ventana de 5 s).
5. Por cada lectura, la Lambda:
   1. Escritura condicional en `Idempotency` (`attribute_not_exists`). Si ya existe, la descarta (RNF-07).
   2. Normaliza unidades y calcula features: L/h, L/ton, deltas y pendiente sobre `MachineState#LAST`.
   3. **Capa 1, reglas**: umbrales por modelo leídos de SSM (con caché).
   4. **Capa 2, estadística**: z-score contra el baseline EWMA propio y el de la cohorte (modelo + zona).
   5. **Capa 3, ML**: IsolationForest (modelo cargado desde S3 en el *init*, versión indicada en SSM `/model/active_version`).
   6. Combina todo en el **health score** y la **severidad**, con las top-3 variables contribuyentes (explicabilidad).
   7. Actualiza `MachineState` (agregados con `ADD`, baseline, LAST) y `Machines` (status, health).
   8. Envía la lectura cruda a **Firehose** (`PutRecordBatch`).
   9. Si la severidad es ≥ Media → escribe en `Anomalies` y publica `AnomalyDetected` en **EventBridge**, con `correlation_id`.
6. Los mensajes fallidos se devuelven en `batchItemFailures`. Tras 3 intentos van a la **DLQ** → alarma CloudWatch → SNS `platform-alarms`.
7. **Firehose** acumula 5 min / 64 MB, convierte a **Parquet** con el esquema de Glue y escribe en `s3://lake/telemetry/operation_id=…/dt=…/machine_type=…/`.
8. **DynamoDB Streams** de `Machines` → Lambda `replicar` → Firestore `machines/{id}`. El mapa del frontend se actualiza por listener (RF-05, RF-15.3).

### Flujo B — Gestión automatizada de incidente (Step Functions `GestionIncidente`)

1. La **regla de EventBridge** (`detail-type = AnomalyDetected`, severidad ≥ Media) inicia la ejecución. El nombre de la ejecución es `machine_id-ventana` para evitar duplicados.
2. **Estado `CrearIncidente`** (SDK DynamoDB `PutItem` con condición "no hay incidente abierto para esta máquina"). Si ya existe → `Choice` → agrega la anomalía al incidente abierto y termina (dedup, RF-10.5).
3. **`Parallel` de enriquecimiento:**
   - Rama 1: Lambda `ia-gemini` → diagnóstico (causa probable, acción sugerida, confianza) a partir de las variables top-3, el historial de la máquina y la cohorte.
   - Rama 2: Lambda `correlacion-zona` → si hay ≥ 3 máquinas afectadas en la zona en 30 min, crea o une el **incidente padre** y Gemini sugiere la causa común (RF-12).
   - Rama 3: consulta de `Inventory` y `Catalog` → disponibilidad de los repuestos probables. Si falta stock → evento `PartShortage` (RF-04.6).
4. **`Choice` por severidad:** si es Crítica → cambia la máquina a `REQUIERE_INTERVENCION` y prioriza la asignación. Si es Baja o Info → solo registra y notifica al dashboard.
5. **Lambda `scoring-tecnicos`** → elige el mejor técnico y guarda el puntaje de cada candidato en el incidente (TRZ-03).
6. **`Map` de notificaciones** sobre los roles de `NotificationRules`: Lambda `notificar` genera el contenido por rol (técnico: detalle técnico; gerencia: impacto) y lo envía por SNS email, webhook, Lambda `notify-push` → **FCM** y Lambda `notify-telegram` → **Telegram** (botones inline).
7. **Crear canal de incidente** en Firestore `incidents/{id}/channel` con los participantes automáticos (operador, técnico, mantenimiento, supervisor de zona) (RF-16.1).
8. **`EsperarAceptacion`** (`lambda:invoke.waitForTaskToken`): guarda el `task_token` en `Incidents`. `TimeoutSeconds = 900` (crítico) o `3600` (alta).
   - El técnico acepta → `POST /v1/incidents/{id}/ack`, un botón inline de Telegram (`ack:<id>:accept`) o un mensaje en el chat → `/bridge/events` (API key) → Lambda → **`SendTaskSuccess`**.
   - Timeout → `Catch States.Timeout` → **escalamiento**: siguiente técnico del ranking + notificación a mantenimiento (RF-06.5, RF-10.4). Máximo 2 escalamientos.
9. **`EsperarResolucion`** (segundo `waitForTaskToken`, timeout de 24 h): se cierra con `POST /v1/incidents/{id}/resolve` (componentes reemplazados, costo, downtime).
10. **Cierre:** Lambda `ia-gemini` resume la conversación de Firestore y extrae causa, acciones y repuestos (RF-16.8). `UpdateItem` del incidente (`CERRADO`, MTTR), descuento de `Inventory`, registro en `MaintenanceRecord` y marca de vigilancia de **reincidencia** de 7 días (RF-11.3).
11. Cada cambio de estado del incidente publica `IncidentStateChanged` en el bus `fleet-events` → Lambda `auditoria` (tabla `audit-events` + historial `EVT#` en `incidents`); el Stream de `Incidents` alimenta a `replicar` (Firestore). El ARN de ejecución de Step Functions queda enlazado al incidente (TRZ-08).

### Flujo C — Consulta del usuario (frontend → API → datos)

1. El usuario abre la app: **Firebase Hosting** entrega el SPA (HTTPS, CDN; alternativa CloudFront → S3 con OAC fuera del Learner Lab).
2. Login en **Cognito** → recibe ID/Access token (JWT con grupos y zona).
3. El frontend llama a `GET /v1/machines?zone=norte` con `Authorization: Bearer <JWT>`.
4. El **Cognito authorizer** de API Gateway valida firma, expiración y audiencia.
5. **Lambda `api-lectura`** valida RBAC y zona → `Query` a DynamoDB. Solo `auditoria` corre dentro de la VPC aislada (TAREA-16); las Lambdas API quedan fuera porque también hablan con otros servicios.
6. La respuesta JSON vuelve por API Gateway. En paralelo, los listeners de **Firestore** mantienen el mapa y la cola de incidentes en tiempo real.

### Flujo D — Comunicación del incidente (chat)

1. Técnico, operador y supervisor escriben en `incidents/{id}/messages` de **Firestore** (texto, mensajes rápidos, ubicación). El campo opcional `attachment_path` guarda una referencia, no un binario.
2. Sin red, el SDK de Firestore encola localmente y sincroniza al volver la conexión (RF-16.6).
3. Un mensaje de tipo `cambio_estado` (o el webhook de Pub/Sub `/bridge/push` con OIDC) llega a `/bridge/events` (API key) → Lambda → actualiza `Incidents` y/o `SendTaskSuccess` (RF-16.5).
4. Las @menciones generan un push **FCM** dirigido (o un mensaje de Telegram).
5. Al cierre, el hilo completo se registra como resumen (`ai_diagnosis` del cierre) y queda en el historial append-only `EVT#` en `incidents` (RF-16.7).

### Flujo E — Análisis programado (Step Functions `AnalisisDiario`)

1. **EventBridge Scheduler** (diario a las 05:00 America/Lima) inicia la ejecución.
2. **`Parallel` de 4 ramas**, cada una con Athena (`StartQueryExecution.sync`) y una Lambda de cálculo:
   - **Preventivo**: horas reales + intensidad (carga, RPM) + health → próxima fecha. Marca mantenimientos innecesarios y atrasados (RF-03).
   - **Repuestos**: mantenimientos previstos + fallas predichas → demanda por almacén, stock mín./máx., consumo irregular (RF-04).
   - **Combustible**: L/h y L/ton contra pares e historial, tendencia progresiva (RF-07).
   - **Productividad**: utilización, máquinas ociosas o sobreexplotadas, matriz productividad × costo (RF-08).
3. Los resultados se escriben en DynamoDB (`Machines.next_maintenance`, `Inventory.recommended_*`, tabla `insights`).
4. Lambda `ia-gemini` genera el resumen ejecutivo → `notificar` (rol `admin` y `gerencia`).
5. Estado `ExportarGCP` (Lambda `export-gcp`) sube a **BigQuery** el lake diario, los incidentes cerrados e insights (réplica DR cross-cloud, §2.8) → tablero de **Looker Studio** para Gerencia.

### Flujo F — Reentrenamiento (Step Functions `Reentrenamiento`)

1. Scheduler semanal (o ejecución manual) → Athena extrae una ventana de 90 días con etiquetas de falla.
2. Una Lambda (container ECR, 3–10 GB de memoria, ≤ 15 min) entrena el IsolationForest y calcula precision/recall sobre los escenarios etiquetados.
3. **`Choice`**: si la métrica nueva es ≥ la actual → guarda `models/vN+1/` en S3 y actualiza SSM `/model/active_version`. Si no → registra el resultado y descarta el modelo.
4. Las Lambdas `procesar` toman el nuevo modelo en su siguiente *cold start*, o al detectar un cambio de versión en SSM (caché de 5 min).

### Flujo G — Observabilidad y heartbeat (transversal)

1. Todas las Lambdas emiten logs JSON (Powertools) con `correlation_id`, `machine_id` e `incident_id`. Retención de 7 días.
2. Métricas EMF por servicio y severidad (sin `machine_id` como dimensión) → dashboards técnico y de negocio.
3. Alarmas (DLQ > 0, errores > 1 %, SFN fallida, `ApproximateAgeOfOldestMessage` > 60 s, throttles) → SNS `platform-alarms`.
4. **X-Ray** traza API Gateway → Lambda → Step Functions → Lambda IA, incluyendo la llamada saliente a GCP como subsegmento.
5. La Lambda `heartbeat` (cada 5 min) detecta máquinas silenciosas → evento `MachineSilent` → incidente de severidad Media.
