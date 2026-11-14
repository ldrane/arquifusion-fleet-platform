# arquifusion_ml

- **Dueño:** Persona A
- **Qué hace:** definiciones compartidas entre el simulador, `procesar` (inferencia) y `retrain` (entrenamiento): variables del modelo, esquema del lake y artefactos del modelo. Si cambia aquí, cambia para los tres a la vez.
- **Consume / produce:** nada en runtime; es una librería pura (sin dependencias).
- **Cubre:** RF-02, RF-09, RF-13.2, MH-AI-04.
- **Uso:** se copia dentro de las imágenes ECR de `procesar` y `retrain`. En local: `pip install -e services/ml`.
- **Cómo probar:** `pytest services/ml/tests`
