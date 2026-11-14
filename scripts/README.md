# Scripts

| Script | Dueño | Qué hace |
|---|---|---|
| `seed.py` | C | Carga datos maestros idempotentes: máquinas, técnicos, catálogo (componentes + `MODEL#`), inventario, **almacenes** (`{p}-warehouses`, WH-01..04) y reglas de notificación. `export` regenera `contracts/fixtures/seed/` (test: `python -m pytest scripts/tests -q`) |
| `cognito_users.py` | C | Crea/actualiza los usuarios demo de Cognito: `u-op-01`, `u-mant-01`, `u-sup-01`, `u-adm-01`, `u-ger-01` y un `u-tec-XX` por técnico del seed, con grupo (= rol), `custom:zone` y `custom:technician_id` (#8) |
| `build_query_layer.sh` | C | `build/layer-c-gcp.zip` (google-auth) para `infra/query` |
| `build_layer.sh` | A | `build/layer-a-common.zip` para `infra/ingest` |
| `smoke_golden_path.sh` | Todos | Prueba E2E del golden path. Se corre antes de cada merge a `main` desde H2 |

## Usuarios Cognito (después de que B aplique `infra/base`)

```bash
export DEMO_PASSWORD='<contraseña-demo>'          # nunca en el repo; cumple la política del pool
python scripts/cognito_users.py --stage dev        # busca el pool arquifusion-dev*; o --user-pool-id us-east-1_XXX
python scripts/cognito_users.py --stage c --create-groups   # lab personal sin los grupos de B
```

## Smoke del golden path (#27)

```bash
export API_URL=https://<api-id>.execute-api.us-east-1.amazonaws.com/v1   # stage v1; rutas sin /v1
export SIMULATOR_API_KEY=<api-key-ingest>
export COGNITO_CLIENT_ID=<app-client-id> TEC_PASSWORD="$DEMO_PASSWORD"   # o JWT_TECNICO=<id-token de u-tec-07>
bash scripts/smoke_golden_path.sh
```

Qué verifica: `GET /me` del técnico trae `technician_id=TEC-07` → `python -m simulator stream --scenario degradacion --machine EX-023`
→ espera `GET /incidents?machine_id=EX-023` en `assigned` a TEC-07 → `POST /incidents/{id}/ack` (accept) → `in_progress`
→ `POST /incidents/{id}/resolve` → `closed` con `resolution_summary` (resumen IA). Si ya hay un incidente abierto en EX-023 lo reutiliza.
Opcionales: `JWT_MANT` (reasigna a TEC-07 si la SFN eligió a otro), `SPEEDUP` (600), `TIMEOUT_DETECT_S` (900), `SMOKE_SKIP_SIM=1`.
Requiere `curl`, `aws` (solo si no se pasa `JWT_TECNICO`) y el venv con las dependencias del simulador.
