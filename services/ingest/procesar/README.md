# procesar

- **Dueño:** Persona A
- **Qué hace:** por cada lectura: idempotencia, capa 1 reglas por tipo de máquina, capa 2 z-score EWMA (propio y de cohorte tipo+zona), capa 3 IsolationForest. Las combina en `health_score`, `severity` y top-3 factores (explicabilidad). Las lecturas en alerta no alimentan el baseline.
- **Consume:** SQS `{p}-ingest` (lotes ≤100 de `POST /telemetry`, envueltos con `correlation_id`), SSM `thresholds/{type}` y `model/active_version`, modelo en `s3://{p}-artifacts-*/models/isolation_forest/`.
- **Produce:** `machine-state` (BASELINE, cohorte, LAST, AGG por hora), `machines` (status, severity, health, factores, última lectura), `anomalies` (severidad ≥ medium), Firehose → lake y `AnomalyDetected` (solo si no hay incidente abierto ni bloqueo de 10 min, contratos.md §9).
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
