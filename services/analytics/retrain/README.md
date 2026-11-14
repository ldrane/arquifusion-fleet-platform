# retrain

- **Dueño:** Persona A
- **Qué hace:** pasos de la SFN `Reentrenamiento`. `handler.handler` entrena un IsolationForest candidato (solo lecturas `operating`; etiquetas = ventanas precursoras de `labels/failures.parquet`; umbral calibrado por F1; precision/recall y anticipación media en un 20 % final de prueba). `handler.promote` lo activa.
- **Consume:** resultado CSV de Athena (`training.sql`, 90 días) y `s3://<lake>/labels/failures.parquet`.
- **Produce:** `s3://<artifacts>/models/isolation_forest/vN/{model.joblib,metadata.json}`; al promover, SSM `/arquifusion/<stage>/model/active_version` e `insights` `ml_model` (GET /v1/ml/model).
- **Cubre:** RF-13.2, MH-AI-04, MH-SFN-03, TRZ-05.
- **Contrato con `procesar`:** score = `-model.score_samples(X)` (0-1) comparado con `metadata.score_threshold`; puntuar solo lecturas con `state` en `metadata.extra["scored_states"]`. `scikit-learn==1.9.*` en ambas imágenes.
- **Primer modelo (local):** `.venv/bin/python services/analytics/retrain/train_local.py --lake data/lake --out build/models` y luego subir `build/models/v1/` y fijar SSM (instrucciones en el docstring).
- **Despliegue:** imagen ECR `retrain-<tag>` construida desde la raíz (`Dockerfile`), 3008 MB, 900 s (`infra/ingest/retrain.tf`).
- **Cómo probar:** `pytest services/analytics/retrain/tests`
