# sim-driver · gemelo de flota serverless

- **Qué hace:** Lambda en contenedor que genera y envía telemetría real a `POST /telemetry` sin depender de la laptop del equipo. EventBridge Scheduler la invoca cada minuto; solo trabaja si el estado en SSM está `enabled`.
- **Estado:** parámetro SSM String `/arquifusion/{stage}/sim/state` (JSON): `enabled`, `scenario`, `machines`, `zone`, `speedup`, `interval_s`, `started_at`, `expires_at`, `requested_by`, `correlation_id`. Lo escriben las rutas `POST /sim/scenario` y `POST /sim/stop` de `api-comandos` (TAREA-08).
- **Lógica (`service.py`, sin AWS):** valida habilitado/vigencia, carga la flota del seed, resuelve objetivos con la misma regla que `simulator/cli.py`, y ejecuta hasta `floor(50 / interval_s)` ticks mientras queden más de 8 s de Lambda. No importa `simulator.cli` ni `simulator.history` (pandas/pyarrow).
- **Handler:** `api_url` desde SSM `/arquifusion/{stage}/api/url`; API key desde Secrets Manager `arquifusion/{stage}/simulator/api-key` (acepta texto plano o el JSON `{api_key, api_url, operation_id}`). Env: `STAGE`, `SIM_STATE_PARAM`.
- **Imagen:** `services/ingest/sim_driver/Dockerfile` (build desde la raíz del repo; incluye `simulator/` y `contracts/fixtures/seed/`). Tag `sim-driver-<IMAGE_TAG>` en el repo ECR `arquifusion-<stage>-ml`.
- **Infra:** `infra/ingest/sim.tf` (Lambda `package_type=Image`, 60 s, 512 MB, concurrencia reservada 1, Scheduler cada minuto, parámetro SSM con `ignore_changes`).
- **Tests:** `PYTHONPATH=services/shared python -m pytest -q services/ingest/sim_driver`.
