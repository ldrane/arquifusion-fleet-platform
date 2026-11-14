# Simulador de flota

- **Dueño:** Persona A
- **Qué hace:** genera telemetría realista de una flota determinista (84 máquinas: 24 `excavator` EX, 25 `mining_truck` CM, 12 `loader` CF, 10 `bulldozer` BD, 13 `drill` PF) en 4 zonas de una mina ficticia del sur del Perú. La envía en vivo a `POST /telemetry` o genera historial sintético con fallas etiquetadas para el data lake.
- **Consume:** nada (opcional: `SIMULATOR_API_URL`, `SIMULATOR_API_KEY`).
- **Produce:** lotes `TelemetryBatch` (≤100 lecturas, `contracts/openapi.yaml`) y Parquet con el esquema de `arquifusion_ml.lake`.
- **Cubre:** RF-01, requerimientos §5.6 (escenarios 1-5), insumo de RF-02, RF-07, RF-08, RF-09, RF-12 y RF-13.

## Módulos

| Archivo | Responsabilidad |
|---|---|
| `fleet.py` | Flota determinista por semilla: IDs, modelos, zonas, coordenadas y baselines por tipo |
| `scenarios.py` | Los 6 escenarios como efectos sobre la lectura (`Effect`) |
| `generator.py` | Lecturas válidas según el OpenAPI y `FleetSimulator` (modo stream) |
| `sender.py` | Cliente de `POST /telemetry`: lotes ≤100, `x-api-key`, `X-Correlation-Id`, reintentos con backoff |
| `history.py` | Historial Parquet particionado como Firehose + `labels/failures.parquet` |
| `cli.py` | `python -m simulator {stream,history,fleet}` |

## Escenarios (`--scenario`)

| Escenario | Efecto | Máquinas por defecto |
|---|---|---|
| `normal` | Sin anomalías | — |
| `degradacion` | Temperatura (+28 °C), vibración (×2.6) y combustible (×1.3) suben progresivamente en 48 h simuladas | `EX-001` |
| `falla_subita` | Salto de temperatura (+40 °C) y vibración (×3.5), caída de presión | `CM-001` |
| `combustible` | Consumo ×1.5 progresivo con carga normal | `BD-001` |
| `grupal_zona` | Combustible contaminado: 6 máquinas de `norte` con el mismo patrón | 6 de `norte` |
| `ociosa` | IDs pares ociosas (`ociosa`), impares sobreexplotadas (`sobreexplotada`) | 4 `loader` |

`--machine` (repetible) y `--zone` cambian las máquinas afectadas. Las lecturas afectadas llevan `sim_scenario` con la etiqueta; el resto, `null`.

## Uso

```bash
export SIMULATOR_API_URL=https://<api-id>.execute-api.us-east-1.amazonaws.com/v1
export SIMULATOR_API_KEY=<api-key-del-simulador>   # nunca en el repo

# Demo: degradación de EX-023 en ~48 min (speedup 60 = 1 min real = 1 h simulada)
python -m simulator stream --scenario degradacion --machine EX-023 --rate 2

# Incidente grupal en la zona sur durante 10 minutos
python -m simulator stream --scenario grupal_zona --zone sur --duration 10

# Sin API: ver los lotes que se enviarían
python -m simulator stream --scenario falla_subita --duration 1 --dry-run --out lotes.jsonl

# Historial de 90 días (lectura cada 15 min, ~725 mil filas, ~30 s) y subida al lake
python -m simulator history --days 90d --out data/lake --upload s3://<bucket-lake>

# Flota en JSON (para los seeds de la Persona C)
python -m simulator fleet --out data/fleet.json
```

Opciones globales: `--seed` (default 42; misma semilla = misma flota y mismas lecturas).

## Historial y etiquetas

- Ruta: `data/lake/telemetry/operation_id=OP-01/dt=YYYY-MM-DD/machine_type=<tipo>/part-00000.parquet`, columnas = `LAKE_COLUMNS` (`ts` como `timestamp[ms, UTC]`). `health_score`, `severity` y `correlation_id` van en `null`.
- Turnos de 06:00 a 22:00 (Lima); fuera de turno la máquina está `stopped`.
- Fallas (≈1 por máquina cada 90 días + 2 eventos grupales): `degradacion` (precursor de 24-72 h), `combustible` (12-48 h), `falla_subita` (0.5-2 h), `grupal_zona` (12 h). Durante el precursor las lecturas operativas llevan la etiqueta; tras `failure_at` la máquina queda en `maintenance` de 8 a 24 h.
- `data/lake/labels/failures.parquet`: verdad de referencia (`machine_id`, `kind`, `precursor_start`, `failure_at`, `repair_end`) para calcular precision, recall y `mean_lead_time_hours`.
- 3 máquinas crónicamente ociosas y 3 sobreexplotadas, sin etiqueta (no son fallas), para la analítica de productividad.

## Cómo probar

```bash
.venv/bin/pytest simulator -q
```
