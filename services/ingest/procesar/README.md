# procesar

- **Dueño:** Persona A
- **Qué hace:** por cada lectura: idempotencia, descarte de máquinas no sembradas (#1, métrica `ReadingsUnknownMachine`), capa 1 reglas **por modelo** (μ±3σ warn / μ±4σ crit del `nominal` del seed, #2; las reglas "low" solo con la máquina operando), capa 2 z-score EWMA solo en estado `operating` (propio con piso σ nominal, y de cohorte tipo+zona estandarizada por modelo), capa 3 IsolationForest. Las combina en `health_score`, `severity` y top-3 factores (explicabilidad). Las lecturas en alerta no alimentan el baseline.
- **Consume:** SQS `{p}-ingest` (lotes ≤100 de `POST /telemetry`, envueltos con `correlation_id`), `machines` (modelo/tipo/zona del seed), SSM `thresholds/{model}` (override opcional) y `model/active_version`, modelo en `s3://{p}-artifacts-*/models/isolation_forest/`.
- **Produce:** `machine-state` (BASELINE, cohorte, LAST, AGG por hora con `health_score`), `machines` (solo campos dinámicos: status, severity, health, factores, location, operating_hours, última lectura; nunca crea ítems, `attribute_exists(pk)`), `anomalies` (severidad ≥ medium, con `zone` + `detected_at` para el GSI `by_zone`, #7), Firehose → lake y `AnomalyDetected` (solo si no hay incidente abierto ni bloqueo de 10 min, contratos.md §9).
- **Umbrales:** `thresholds_default.json` se genera del seed con `python services/ingest/procesar/ingest_procesar/rules.py` (un test verifica que esté sincronizado).
- **Cubre:** RF-02, RF-09, RNF-07, MH-AI-01.
- **Despliegue:** imagen ECR (`infra/ingest/procesar.tf`), fuera de la VPC. Build desde la raíz: `docker build -f services/ingest/procesar/Dockerfile -t <repo>:procesar-<tag> .`
- **Cómo probar:** `.venv/bin/pytest services/ingest/procesar`

| Módulo | Responsabilidad |
|---|---|
| `service.py` | Orquesta el lote: idempotencia, evaluación por máquina, escrituras, emisión |
| `ingest_procesar/message.py` | Envoltorio SQS de API Gateway |
| `ingest_procesar/rules.py` | Capa 1 + `thresholds_default.json` |
| `ingest_procesar/baseline.py` | Capa 2: EWMA y z-score (piso de desviación 2 % de la media) |
| `ingest_procesar/model.py` | Capa 3: carga del modelo activo, score `-score_samples` |
| `ingest_procesar/scoring.py` | Riesgo combinado `1 − Π(1 − rᵢ)`, health, severidad, factores |
| `ingest_procesar/repository.py` | DynamoDB, Firehose, EventBridge (keyschema documentado ahí) |
