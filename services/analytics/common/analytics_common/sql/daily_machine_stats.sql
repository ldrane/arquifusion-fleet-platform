-- daily_machine_stats v1 (RF-03, RF-04, RF-07, RF-08, RF-11.4)
-- Una fila por máquina y día de los últimos 90 días. La comparten las 4 ramas de AnalisisDiario y los KPIs,
-- así el lake se escanea una sola vez por ejecución (partición dt).
-- `operation_id` es una partición con proyección `injected` (infra/ingest/lake.tf): Athena EXIGE filtrarla con
-- igualdad (#10). infra/ingest reemplaza 'OP-01' por var.default_operation_id (DEFAULT_OPERATION_ID, contratos §9).
SELECT
  machine_id,
  machine_type,
  dt,
  max(model) AS model,
  max(zone) AS zone,
  count(*) AS readings,
  sum(CASE WHEN state = 'operating' THEN 1 ELSE 0 END) AS operating_readings,
  sum(CASE WHEN state = 'idle' THEN 1 ELSE 0 END) AS idle_readings,
  avg(fuel_rate_lph) AS avg_fuel_lph,
  avg(CASE WHEN state = 'operating' THEN fuel_rate_lph END) AS avg_fuel_lph_operating,
  avg(CASE WHEN state = 'operating' THEN load_pct END) AS avg_load_pct,
  avg(CASE WHEN state = 'operating' THEN rpm END) AS avg_rpm,
  avg(temperature_c) AS avg_temperature_c,
  min(operating_hours) AS min_hours,
  max(operating_hours) AS max_hours
FROM telemetry_raw
WHERE operation_id = 'OP-01'
  AND dt >= date_format(current_date - INTERVAL '90' DAY, '%Y-%m-%d')
GROUP BY machine_id, machine_type, dt
