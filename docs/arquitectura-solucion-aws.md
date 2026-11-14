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
    CF["CloudFront<br/>+ OAC"]
    S3WEB[("S3 frontend<br/>privado")]
    COG["Cognito<br/>User Pool + grupos"]
    APIGW["API Gateway REST<br/>/telemetry (API key)<br/>/v1/* (Cognito JWT)"]
  end

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
    LAPI["Lambdas API lectura/escritura<br/>(VPC aislada)"]
    LASSIGN["Lambda scoring técnicos"]
    LCORR["Lambda correlación zona"]
    LNOTIF["Lambda notificar por rol"]
    LREPL["Lambda replicar a GCP"]
    LAI["Lambda IA (cliente Gemini)"]
    LHB["Lambda heartbeat"]
  end

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
    GEM["Vertex AI / Gemini"]
    FS[("Firestore<br/>chat + réplica")]
    PS["Pub/Sub"]
    CFN["Cloud Function Gen2"]
    FCM["Firebase Cloud Messaging"]
    GCS[("GCS / BigQuery<br/>réplica analítica")]
  end

  SIM -->|HTTPS + x-api-key| APIGW
  WEB --> CF --> S3WEB
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
  SFN1 --> LAI --> GEM
  SFN1 --> LCORR
  SFN1 --> LASSIGN
  SFN1 --> LNOTIF
  SFN1 --> DDB
  LNOTIF --> SNS
  LNOTIF --> PS --> CFN --> FCM
  CFN -->|ack técnico| APIGW

  SCH --> SFN2
  SCH --> SFN3
  SCH --> LHB
  SFN2 --> ATH
  SFN3 --> ATH
  SFN3 --> S3M
  ATH --> GLUE
  ATH --> S3L

  DDB -->|Streams| LREPL --> FS
  SFN2 -->|export diario| GCS

  LAPI --> DDB
  SM -.-> LAI
  SM -.-> LREPL
  SM -.-> LNOTIF
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
│  API Gateway REST  ── Cognito authorizer ──  CloudFront ─(OAC)─ S3 frontend    │                   │
└───────┬──────────────────────────────┬─────────────────────────────────────────┼───────────────────┘
        │ /telemetry                   │ /v1/*                                   │
┌───────▼──────────── INGESTA ─────────▼─────────────── VPC "datos" (aislada) ───┼───────────────────┐
│  SQS ingest ─► Lambda procesar      │ Lambdas API ─► Gateway Endpoints         │                   │
│      └─► DLQ    (ECR container)     │   (subred privada, sin internet)         │                   │
└───────┬─────────────────────────────┴──────────────────────────────────────────┼───────────────────┘
        │                                                                        │
┌───────▼────────────────────────────── DATOS ───────────────────────────────────┼───────────────────┐
│  DynamoDB (PITR, Streams) │ Firehose ─► S3 lake (Parquet) ─► Glue ─► Athena    │                   │
└───────┬──────────────────────────────────────────────────────────────────┬─────┼───────────────────┘
        │ AnomalyDetected                                     Streams      │     │
┌───────▼──────────────── ORQUESTACIÓN ───────────────────┐   ┌────────────▼─────▼───── GCP ─────────┐
│  EventBridge ─► SFN GestionIncidente                     │   │  Firestore (chat, réplica, realtime) │
│  Scheduler   ─► SFN AnalisisDiario / Reentrenamiento     │◄─►│  Gemini · Pub/Sub · Cloud Function   │
│              ─► Lambda heartbeat                          │   │  FCM · GCS/BigQuery (réplica)        │
└──────────────────────────────────────────────────────────┘   └──────────────────────────────────────┘
  Transversal: Secrets Manager · SSM · CloudWatch · X-Ray · SNS · LabRole · KMS (claves AWS-managed)
```

---

## 2. Stack tecnológico y justificación

### 2.1 Borde y acceso

| Servicio | Configuración | Problema que resuelve | Cubre |
|---|---|---|---|
| **Amazon CloudFront** | Distribución con origen S3 vía **OAC**, solo HTTPS, `PriceClass_100` | Sirve el frontend con TLS sin bucket público | RF-15, RNF-08, MH-SEC-05 |
| **Amazon S3 (frontend)** | Bucket privado, Block Public Access ON, SSE-S3 | Hosting estático serverless | RF-15, RNF-02 |
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
| **Lambda `ia-gemini`** | Cliente de Vertex AI/Gemini con credencial desde Secrets Manager. Diagnóstico, resumen por rol, causa común, resumen del chat al cierre y tool-calling del asistente. Fallback a plantilla determinista | RF-02.6, RF-07.4, RF-10.3, RF-12.3, RF-14, RF-16.8, MH-MC-03 |
| **Lambda `notificar`** | Enruta por la tabla `NotificationRule` (rol × severidad × tipo). Canales: SNS (email), webhook (Slack/Discord) y Pub/Sub → FCM. Dedup con TTL | RF-10.1/10.2/10.5 |
| **Lambda `replicar`** | DynamoDB Streams → Firestore (máquinas, incidentes, técnicos) | MH-HA-03, MH-MC-01 |
| **Lambda `auditoria`** | DynamoDB Streams → tabla `AuditEvents` append-only (antes/después, actor, motivo) | RNF-15, TRZ-02/06 |
| **Lambda `heartbeat`** | Marca `SILENT` las máquinas sin lectura en más de 3× su frecuencia → evento `MachineSilent` | OBS-09 |
| **Lambdas API** (`/v1/*`) | CRUD de lectura y acciones (`ack`, `assign`, `resolve`, `timeline`). `ack` llama a `SendTaskSuccess` | §5.5, RF-06.4, TRZ-09 |
| **Amazon SNS** | Topics por rol (`alerts-tecnico`, `alerts-mantenimiento`, `alerts-gerencia`) + topic `platform-alarms` | RF-10.2, MH-OBS-03 |
| **AWS Secrets Manager** | `gcp/service-account`, `gemini/api-key`, `webhook/slack`, `simulator/api-key`, `bridge/gcp-api-key` | Rúbrica (variables globales), MH-SEC-03 |
| **SSM Parameter Store** | `/arquifusion/{stage}/thresholds/*`, `/model/active_version`, `/prompts/version` (String/SecureString estándar, gratis) | RF-02.1, TRZ-05 |
| **Amazon CloudWatch** | Logs JSON (Powertools), retención de 7 días, métricas EMF sin `machine_id` como dimensión, 2 dashboards, alarmas → SNS | RNF-09, OBS-01–07, MH-OBS |
| **AWS X-Ray** | Tracing activo en Lambda, API Gateway y Step Functions | OBS-02, MH-OBS-07 |
| **KMS (claves AWS-managed)** | `aws/s3`, `aws/sqs`, `aws/secretsmanager`. DynamoDB con su clave propia | RNF-08, MH-SEC-04 |
| **IAM `LabRole`** | Único rol de ejecución en todo el stack | W-01, MH-IAC-03 |
| **Terraform** (providers `aws` + `google`) | Estado en S3 con `use_lockfile` | RNF-10, MH-IAC-02 |

### 2.6 Modelo de datos en DynamoDB

| Tabla | PK | SK | GSI | Notas |
|---|---|---|---|---|
| `Machines` | `operation_id#machine_id` | `META` | `GSI1: zone → status` | Estado, health score, próximo mantenimiento |
| `MachineState` | `machine_id` | `AGG#1h#2026-11-13T10` / `BASELINE` / `LAST` | — | Agregados 1 min/1 h/1 d, baseline EWMA y última lectura (ESC-07) |
| `Idempotency` | `machine_id#timestamp` | — | — | Escritura condicional, TTL 24 h (RNF-07) |
| `Anomalies` | `machine_id` | `ts#anomaly_id` | `GSI1: zone#date → ts` | Variables, score, `model_version`, tipo (individual/cohorte/tendencia) |
| `Incidents` | `incident_id` | `META` / `EVT#ts` | `GSI1: machine_id → t_detección`, `GSI2: status#severity → ts` | Incluye `task_token`, `parent_incident_id`, `correlation_id` |
| `Technicians` | `tech_id` | `META` | `GSI1: available → zone` | Especialidades, ubicación y carga |
| `Inventory` | `location_id` | `component_id` | `GSI1: component_id` | Stock, mín. y máx. |
| `Catalog` | `component_id` / `model_id` | `COMPAT#…` | — | Componentes y compatibilidades |
| `NotificationRules` | `role` | `severity#event_type` | — | Canales y plantilla |
| `AuditEvents` | `entity#entity_id` | `ts#event_id` | — | Append-only (sin `UpdateItem` desde la app) |

### 2.7 Componentes en GCP (rol real, no decorativo)

| Servicio GCP | Rol | Cubre |
|---|---|---|
| **Vertex AI / Gemini** | LLM de diagnóstico, resúmenes y asistente con function calling | RF-02.6, RF-14, RF-16.8 |
| **Firestore** | Canales de incidente (chat), estado en tiempo real del mapa, **persistencia offline** en el móvil y réplica de entidades críticas | RF-05, RF-15.3, RF-16, MH-HA-03 |
| **Pub/Sub + Cloud Function Gen2** | Recepción de eventos desde AWS → envío push FCM. Puente inverso a AWS cuando el técnico acepta desde el chat | RF-10.2, RF-16.5 |
| **Firebase Cloud Messaging** | Push al móvil del técnico u operador | RF-10.2 |
| **GCS / BigQuery** | Réplica diaria del lake (export Parquet) | RNF-04/05 |

---

## 3. Diseño de red y seguridad

### 3.1 Principio de diseño

La plataforma es **serverless y sin cómputo expuesto**. El perímetro lo forman servicios administrados por AWS (CloudFront, API Gateway, Cognito), que ya son multi-AZ y con TLS. Por eso:

- **No hay subredes públicas, Internet Gateway ni NAT Gateway.** Un NAT cuesta ~USD 32/mes + datos, consume el presupuesto del lab y no es pago por uso (MH-NET-01).
- Se usa **una VPC aislada solo para la zona de datos**: las Lambdas que leen y escriben exclusivamente DynamoDB y S3 corren en subredes privadas sin salida a internet, accediendo por **Gateway Endpoints** (gratis). Así la ruta de acceso a los datos de la API nunca sale de la red de AWS.
- Las Lambdas que necesitan salir a internet (GCP, webhooks, Athena, Secrets Manager, Step Functions) corren **fuera de la VPC**. Su seguridad se basa en IAM + TLS + secretos gestionados.

### 3.2 Topología de la VPC `arquifusion-data`

```
VPC arquifusion-data  10.20.0.0/16   (us-east-1, DNS hostnames ON, sin IGW, sin NAT)
│
├── Subred privada-aislada A   10.20.1.0/24   us-east-1a
├── Subred privada-aislada B   10.20.2.0/24   us-east-1b
│      └─ Route table "rt-isolated":
│           10.20.0.0/16  → local
│           pl-xxxx (S3)       → vpce-s3   (Gateway Endpoint)
│           pl-yyyy (DynamoDB) → vpce-ddb  (Gateway Endpoint)
│           (sin ruta 0.0.0.0/0)
│
├── Gateway Endpoint S3        (policy: solo buckets arquifusion-*)
└── Gateway Endpoint DynamoDB  (policy: solo tablas arquifusion-{stage}-*)
```

| Elemento | Decisión |
|---|---|
| **Subredes públicas** | Ninguna. No hay recursos que deban tener IP pública. |
| **Subredes privadas** | 2 subredes aisladas en 2 AZ (alta disponibilidad de las ENI de Lambda). |
| **Interface Endpoints** | No se usan (~USD 7/mes por endpoint por AZ). Por eso las Lambdas que llaman a Secrets Manager, Step Functions o Athena quedan fuera de la VPC. |
| **NACL** | Default (stateless allow-all interno). El control fino se hace con SG + endpoint policies. |
| **VPC Flow Logs** | Destino S3 (no requiere rol IAM), formato Parquet, solo `REJECT`, para auditoría a bajo costo. |

**Lambdas dentro de la VPC (zona de datos):** `api-machines`, `api-incidents-read`, `api-inventory`, `api-timeline`, `api-audit`, `auditoria`.
**Lambdas fuera de la VPC:** `procesar` (Firehose y EventBridge), `ia-gemini`, `notificar`, `replicar`, `scoring-tecnicos`, `correlacion-zona`, `heartbeat`, `api-incidents-ack` (Step Functions) y las Lambdas de `AnalisisDiario` y `Reentrenamiento` (Athena).

> **[Probar en F0]** Adjuntar Lambda a VPC con `LabRole` requiere permisos `ec2:CreateNetworkInterface` y relacionados. Si falla, todas las Lambdas quedan fuera de VPC y la VPC se elimina sin afectar el resto del diseño. X-Ray desde Lambdas en VPC sin interface endpoint pierde trazas, por eso esas Lambdas usan solo logs y métricas.

### 3.3 Security Groups

| SG | Asociado a | Inbound | Outbound |
|---|---|---|---|
| `sg-lambda-data` | Lambdas de la zona de datos | **Ninguna regla** (Lambda no recibe tráfico entrante) | TCP 443 → prefix list `com.amazonaws.us-east-1.s3`; TCP 443 → prefix list `com.amazonaws.us-east-1.dynamodb` |

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
| **Datos en tránsito** | TLS 1.2+ en CloudFront y API Gateway. Bucket policies con `aws:SecureTransport = false → Deny`. |
| **Bucket policies** | Frontend: solo el principal `cloudfront.amazonaws.com` con `AWS:SourceArn` de la distribución (OAC). Lake: deny sin TLS y deny `s3:DeleteObject*` excepto lifecycle. |
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
6. **`Map` de notificaciones** sobre los roles de `NotificationRules`: Lambda `notificar` genera el contenido por rol (técnico: detalle técnico; gerencia: impacto) y lo envía por SNS email, webhook y Pub/Sub → Cloud Function → **FCM**.
7. **Crear canal de incidente** en Firestore `incidents/{id}/channel` con los participantes automáticos (operador, técnico, mantenimiento, supervisor de zona) (RF-16.1).
8. **`EsperarAceptacion`** (`lambda:invoke.waitForTaskToken`): guarda el `task_token` en `Incidents`. `TimeoutSeconds = 900` (crítico) o `3600` (alta).
   - El técnico acepta → `POST /v1/incidents/{id}/ack` (o un mensaje rápido en el chat → Cloud Function → `/bridge/ack`) → Lambda → **`SendTaskSuccess`**.
   - Timeout → `Catch States.Timeout` → **escalamiento**: siguiente técnico del ranking + notificación a mantenimiento (RF-06.5, RF-10.4). Máximo 2 escalamientos.
9. **`EsperarResolucion`** (segundo `waitForTaskToken`, timeout de 24 h): se cierra con `POST /v1/incidents/{id}/resolve` (componentes reemplazados, costo, downtime).
10. **Cierre:** Lambda `ia-gemini` resume la conversación de Firestore y extrae causa, acciones y repuestos (RF-16.8). `UpdateItem` del incidente (`CERRADO`, MTTR), descuento de `Inventory`, registro en `MaintenanceRecord` y marca de vigilancia de **reincidencia** de 7 días (RF-11.3).
11. Cada cambio en `Incidents` genera un Stream → Lambda `auditoria` (tabla `AuditEvents`) y Lambda `replicar` (Firestore). El ARN de ejecución de Step Functions queda enlazado al incidente (TRZ-08).

### Flujo C — Consulta del usuario (frontend → API → datos)

1. El usuario abre la app en **CloudFront** → S3 (OAC) entrega el SPA.
2. Login en **Cognito** → recibe ID/Access token (JWT con grupos y zona).
3. El frontend llama a `GET /v1/machines?zone=norte` con `Authorization: Bearer <JWT>`.
4. El **Cognito authorizer** de API Gateway valida firma, expiración y audiencia.
5. **Lambda `api-machines`** (VPC aislada) valida RBAC y zona → `Query` a DynamoDB por el **Gateway Endpoint** (sin salir a internet).
6. La respuesta JSON vuelve por API Gateway. En paralelo, los listeners de **Firestore** mantienen el mapa y la cola de incidentes en tiempo real.

### Flujo D — Comunicación del incidente (chat)

1. Técnico, operador y supervisor escriben en `incidents/{id}/messages` de **Firestore** (texto, mensajes rápidos, ubicación). Las fotos y audios se suben a Cloud Storage con URL firmada.
2. Sin red, el SDK de Firestore encola localmente y sincroniza al volver la conexión (RF-16.6).
3. Un mensaje de tipo `cambio_estado` dispara la **Cloud Function** → `/bridge/*` en API Gateway (API key) → Lambda → actualiza `Incidents` y/o `SendTaskSuccess` (RF-16.5).
4. Las @menciones generan un push **FCM** dirigido.
5. Al cierre, el hilo completo se exporta a S3 (`incidents/{id}/chat.json`) como registro de auditoría (RF-16.7).

### Flujo E — Análisis programado (Step Functions `AnalisisDiario`)

1. **EventBridge Scheduler** (diario a las 05:00 America/Lima) inicia la ejecución.
2. **`Parallel` de 4 ramas**, cada una con Athena (`StartQueryExecution.sync`) y una Lambda de cálculo:
   - **Preventivo**: horas reales + intensidad (carga, RPM) + health → próxima fecha. Marca mantenimientos innecesarios y atrasados (RF-03).
   - **Repuestos**: mantenimientos previstos + fallas predichas → demanda por almacén, stock mín./máx., consumo irregular (RF-04).
   - **Combustible**: L/h y L/ton contra pares e historial, tendencia progresiva (RF-07).
   - **Productividad**: utilización, máquinas ociosas o sobreexplotadas, matriz productividad × costo (RF-08).
3. Los resultados se escriben en DynamoDB (`Machines.next_maintenance`, `Inventory.recommended_*`, tabla `Insights`).
4. Lambda `ia-gemini` genera el resumen ejecutivo → `notificar` (rol `admin` y `gerencia`).
5. Export diario del lake y de los incidentes a **GCS/BigQuery** (réplica analítica cross-cloud).

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
