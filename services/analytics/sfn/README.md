# Step Functions de analítica

- **Dueño:** Persona A
- **Plantillas:** los `${...}` se reemplazan con `templatefile()` en `infra/ingest/analytics.tf` y `retrain.tf` (ARN de las Lambdas, workgroup y base de Athena, SQL escapado).

## `analisis_diario.asl.json` (RF-03, RF-04, RF-07, RF-08, RF-10.3, MH-SFN-02)
Scheduler diario 05:00 America/Lima.
`Contexto` → `EstadisticasDiarias` (Athena `.sync`, `analytics_common/sql/daily_machine_stats.sql`) → `Ramas` (Parallel: preventivo · repuestos · combustible · productividad) → `KpisYReporte` (KPIs + resumen ejecutivo con `ia-gemini`).
- Una sola consulta Athena compartida: el lake se escanea una vez por ejecución (costo).
- Si una rama falla, se registra como `{"status": "failed"}` y el resto del flujo sigue.

## `reentrenamiento.asl.json` (RF-13.2, MH-SFN-03, MH-AI-04)
Scheduler semanal (domingo 04:00 Lima) y manual (`POST /v1/ml/retrain` de B, que inicia la SFN por el ARN publicado en SSM).
`VersionActiva` (SSM, o `v0` si no existe) → `ExtraerDatos` (Athena, `retrain/training.sql`) → `Entrenar` → `EsMejor` (F1 candidato ≥ F1 activo) → `Promover` (SSM `active_version` + `insights` `ml_model`) o `Descartar`.
