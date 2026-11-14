# retrain

- **Dueño:** Persona A
- **Qué hace:** Entrena IsolationForest y calcula métricas (SFN `Reentrenamiento`).
- **Consume:** Ventana de 90 días desde Athena
- **Produce:** `s3://models/isolation_forest/vN/`, SSM `/model/active_version`
- **Cubre:** RF-13.2, MH-AI-04
- **Despliegue:** Imagen de contenedor (ECR). Fuera de la VPC.
- **Cómo probar:** `pytest services/analytics/retrain/tests`
