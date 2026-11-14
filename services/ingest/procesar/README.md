# procesar

- **Dueño:** Persona A
- **Qué hace:** Normaliza lecturas, reglas + z-score + IsolationForest, health score y severidad.
- **Consume:** SQS `ingest` (lotes ≤100 desde `POST /telemetry`)
- **Produce:** `Machines`, `MachineState`, `Anomalies`, Firehose, evento `AnomalyDetected`
- **Cubre:** RF-02, RF-09, RNF-07
- **Despliegue:** Imagen de contenedor (ECR). Fuera de la VPC.
- **Cómo probar:** `pytest services/ingest/procesar/tests`
