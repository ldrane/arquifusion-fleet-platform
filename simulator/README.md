# Simulador de flota

- **Dueño:** Persona A
- **Qué hace:** genera telemetría realista de la flota del **seed v4** (100 máquinas: 25 `excavator` EX, 35 `mining_truck` CM, 15 `loader` CF, 12 `bulldozer` BD, 13 `drill` PF; 19 modelos de 8 marcas) en sus 4 zonas. IDs, modelo, zona, coordenadas, horómetro, `status` inicial y `expected_interval_s` son los de `contracts/fixtures/seed/machines.json`; el baseline de cada variable es el `nominal` [μ, σ] del modelo (`machine_models.json`). Las máquinas que el seed deja en taller (`maintenance`) o en reserva (`stopped`) siguen reportando, con ese `state` y valores de máquina apagada; los escenarios por defecto las saltan. Ruido acotado a ±2.5σ para que la operación nominal no cruce los umbrales de `procesar` (μ±3σ). La envía en vivo a `POST /telemetry` o genera historial sintético con fallas etiquetadas para el data lake.
- **Consume:** `contracts/fixtures/seed/*.json` (o `--seed-dir` / `SIMULATOR_SEED_DIR`); opcional `SIMULATOR_API_URL` (base del stage, `…/v1`), `SIMULATOR_API_KEY` (secreto `arquifusion/<stage>/simulator/api-key`).
- **Produce:** lotes `TelemetryBatch` (≤100 lecturas, `contracts/openapi.yaml`) y Parquet con el esquema de `arquifusion_ml.lake`.
- **Cubre:** RF-01, requerimientos §5.6 (escenarios 1-5), insumo de RF-02, RF-07, RF-08, RF-09, RF-12 y RF-13.

## Módulos

| Archivo | Responsabilidad |
|---|---|
| `fleet.py` | Flota cargada de los seeds: IDs, modelos, zonas, coordenadas, horómetro y baselines por modelo |
| `scenarios.py` | Los 9 escenarios como efectos sobre la lectura (`Effect`) |
| `generator.py` | Lecturas válidas según el OpenAPI y `FleetSimulator` (modo stream) |
| `sender.py` | Cliente de `POST /telemetry`: lotes ≤100, `x-api-key`, `X-Correlation-Id`, reintentos con backoff |
| `history.py` | Historial Parquet particionado como Firehose + `labels/failures.parquet` |
| `cli.py` | `python -m simulator {stream,history,fleet}` |

## Escenarios (`--scenario`)

| Escenario | Efecto | Máquinas por defecto |
|---|---|---|
| `normal` | Sin anomalías | — |
| `degradacion` | Temperatura (+28 °C), vibración (×2.6) y combustible (×1.3) suben progresivamente en 48 h simuladas | `EX-023` (CAT-336, norte; golden path, CMP-014) |
| `falla_subita` | Salto de temperatura (+40 °C) y vibración (×3.5), caída de presión | `CM-004` (BEL-75131, sur) |
| `combustible` | Consumo ×1.5 progresivo con carga normal | `BD-004` (LIE-PR776, este) |
| `grupal_zona` | Combustible contaminado: 6 máquinas de `norte` (sin EX-023) con el mismo patrón | 6 de `norte` |
| `presion` | Pico de presión hidráulica (×1.22) | `BD-003` (CAT-D10T, sur) |
| `electrico` | Caída de RPM (×0.78) por alternador | `CF-001` (CAT-994K, oeste) |
| `neumaticos` | Vibración ×1.9 y velocidad ×0.7 | `CM-001` (CAT-793F, oeste) |
| `ociosa` | IDs pares ociosas (`ociosa`), impares sobreexplotadas (`sobreexplotada`) | 4 `loader` operativos |

`--machine` (repetible) y `--zone` cambian las máquinas afectadas. Las lecturas afectadas llevan `sim_scenario` con la etiqueta; el resto, `null`.

## Uso

```bash
export SIMULATOR_API_URL=https://<api-id>.execute-api.us-east-1.amazonaws.com/v1
export SIMULATOR_API_KEY=<api-key-del-simulador>   # nunca en el repo

# Demo: degradación de EX-023 en ~12 min (speedup 240 = 1 min real = 4 h simuladas; 2 lecturas/min, cada 30 s)
python -m simulator stream --scenario degradacion

# Incidente grupal en la zona sur durante 10 minutos
python -m simulator stream --scenario grupal_zona --zone sur --duration 10

# Sin API: ver los lotes que se enviarían
python -m simulator stream --scenario falla_subita --duration 1 --dry-run --out lotes.jsonl

# Historial de 90 días (lectura cada 15 min, ~725 mil filas, ~30 s) y subida al lake
python -m simulator history --days 90d --out data/lake --upload s3://<bucket-lake>

# Flota que se simula, en JSON
python -m simulator fleet --out data/fleet.json
```

Opciones globales: `--seed` (default 42; misma semilla = mismas lecturas) y `--seed-dir`. `--rate` por defecto = 2 × 60 / `expected_interval_s` (2 lecturas por máquina por minuto, cada 30 s; heartbeat declara silencio a 180 s). Antes era 1/min. `--speedup` por defecto 240 (antes 60). Para el ritmo anterior: `--rate 1 --speedup 60`.

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
