# Step Functions de analítica

- **Dueño:** Persona A
- `analisis_diario.asl.json`: Scheduler diario 05:00 America/Lima. Parallel de 4 ramas (RF-03, RF-04, RF-07, RF-08, MH-SFN-02).
- `reentrenamiento.asl.json`: Scheduler semanal + manual (`POST /v1/ml/retrain`). Choice de promoción del modelo (RF-13.2, MH-SFN-03).
