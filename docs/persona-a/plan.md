# Persona A: plan de trabajo (Datos e IA)

> Dominio: del sensor a la anomalía y de los datos a los insights. Ver la sección "Persona A" de `docs/division-trabajo-backend.md`.
> Alcance de esta iteración: **código + Terraform + tests locales, sin desplegar**.

## Decisiones tomadas

| Tema | Decisión |
|---|---|
| Acceso a Gemini | **API key de Google AI Studio** en Secrets Manager `arquifusion/{stage}/gemini/api-key`. Llamada REST (`generativelanguage.googleapis.com`) con `urllib` o `requests`, sin SDK pesado. Modelo `gemini-2.5-flash`. |
| Recursos de B | Se referencian por convención de nombres (`contratos.md` §9). Nada de `terraform_remote_state`. |
| Lo que A expone a B y C | Parámetros SSM (`contratos.md` §9) y tabla `insights` (`services/ml/arquifusion_ml/insights.py`). |
| Definiciones compartidas | `services/ml/arquifusion_ml/`: variables del modelo, esquema del lake, artefactos del modelo, ítems de Insights. **Solo el manager las modifica.** |
| Empaquetado | `procesar` y `retrain`: imagen de contenedor ECR (repo `{p}-ml`, tags `procesar-<tag>` y `retrain-<tag>`). El resto: zip + capa `{p}-a-common` (`scripts/build_layer.sh`). |
| Python | 3.12. Venv compartido en `.venv` (ya tiene pytest, moto, numpy, pandas, pyarrow, scikit-learn, requests, powertools, `arquifusion_shared` y `arquifusion_ml` editables). |

## Reparto entre workers

| Worker | Entregables | Archivos que le pertenecen |
|---|---|---|
| **W1: Simulador y datos** | A1 simulador (6 escenarios, envío a `POST /telemetry`), A9 historial sintético con fallas etiquetadas (Parquet con el esquema del lake) | `simulator/**` |
| **W2: Hot path** | A2 API GW → SQS + DLQ, A3 `procesar` (3 capas, health, severidad, dedup, Firehose, EventBridge), A5 `heartbeat`, A6 Firehose + lake + Glue + Athena | `services/ingest/**`, `infra/ingest/{ingest,procesar,heartbeat,lake}.tf` |
| **W3: IA y analítica** | A4 `ia-gemini` (6 tasks + fallback), A7 `AnalisisDiario` (4 ramas + KPIs + reporte), A8 `Reentrenamiento` (`retrain` + promoción) | `services/ai/**`, `services/analytics/**`, `infra/ingest/{ai,analytics,retrain}.tf` |
| **Manager** | `services/ml/**`, `infra/ingest/{main,variables,versions,outputs}.tf`, `contracts/**`, `scripts/build_layer.sh`, integración final | — |

Nadie edita archivos de otro worker. Si un worker necesita algo fuera de su zona, lo anota en su reporte final.

## Flujo entre piezas

```
W1 simulador ──POST /telemetry──► W2 API GW → SQS → procesar ──► DynamoDB (machines, machine-state, anomalies)
     │                                         │  └─► Firehose ──► lake S3 (Parquet, esquema arquifusion_ml.lake)
     │ historial Parquet (mismo esquema) ──────┘                         │
     │                                        └─► EventBridge AnomalyDetected ──► (B) SFN ──► W3 ia-gemini
     ▼                                                                   ▼
  lake S3 ◄──────────────────────────────────────────────── W3 Athena ── AnalisisDiario / Reentrenamiento
                                                                         │            │
                                                     insights (C lo lee) ◄┘            └► S3 models/ + SSM active_version ──► procesar
```

## Reglas para todos los workers
- Seguir `CONTRIBUTING.md`: handler delgado + `service.py` puro, `arquifusion_shared` para respuestas/errores/logs, clientes boto3 fuera del handler, secretos solo en Secrets Manager/SSM, idempotencia, `correlation_id` en todo, docstrings con el RF.
- Tests con `pytest` + `moto`, contra los fixtures de `contracts/fixtures/`. Ejecutar con `.venv/bin/pytest <ruta>`.
- Terraform: solo tus archivos, `LabRole` como rol, nombres `{local.prefix}-...`, logs con retención `var.log_retention_days`. Validar con `terraform -chdir=infra/ingest validate` (ya está hecho `init -backend=false`; no lo repitas).
- No instalar paquetes en `.venv`; si falta uno, repórtalo.
- No hacer commits ni pushes.
