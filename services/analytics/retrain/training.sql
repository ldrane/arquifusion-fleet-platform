-- training v1 (RF-13.2): ventana de 90 días con las variables del modelo (arquifusion_ml.features.RAW_FEATURES)
-- y la etiqueta del simulador. Las ventanas de falla se leen de s3://<lake>/labels/failures.parquet.
-- `operation_id` (proyección `injected`) se filtra con igualdad (#10); infra/ingest reemplaza 'OP-01' por
-- var.default_operation_id.
SELECT
  machine_id,
  ts,
  sim_scenario,
  state,
  temperature_c,
  vibration_mm_s,
  pressure_bar,
  fuel_rate_lph,
  load_pct,
  rpm,
  speed_kmh
FROM telemetry_raw
WHERE operation_id = 'OP-01'
  AND dt >= date_format(current_date - INTERVAL '90' DAY, '%Y-%m-%d')
