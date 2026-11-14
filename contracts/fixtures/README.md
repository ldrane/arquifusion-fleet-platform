# Fixtures de contrato

Ejemplos canónicos de cada interfaz. **Productor y consumidor prueban contra el mismo archivo.**
Si cambia un contrato: primero `contratos.md` / `openapi.yaml`, luego el fixture y recién después el código.
Las fixtures de `api/`, `ia/`, `internal/` y `events/` son coherentes con los seeds (EX-023 = `CAT-336`/norte con las
coordenadas de `seed/machines.json`, técnicos y componentes reales): lo verifica `scripts/tests/test_contract_fixtures.py`.

| Carpeta | Interfaz | Productor → Consumidor |
|---|---|---|
| `events/` | EventBridge bus `arquifusion-{stage}-fleet-events` (formato `aws events put-events --entries file://...`; las fixtures usan `arquifusion-dev-fleet-events`) | A/B → B |
| `pubsub/` | Mensaje del topic `notificaciones` (contratos.md §4) | B (`notificar`) → Cloud Function `notify_bridge` |
| `ia/` | Invocación `ia-gemini` (contratos.md §8.1) | B (SFN) → A |
| `internal/` | `scoring`, `correlacion` (contratos.md §8.3, §8.4) | B (SFN) → B |
| `api/` | Cuerpos REST y eventos API Gateway de ejemplo (`get_me.event.json`, `technician_status.event.json`: técnico TEC-07 con `custom:technician_id`) | Simulador / front → API |
| `seed/` | Datos maestros. **Generados**: `python scripts/seed.py export` (deben coincidir byte a byte con `seed_data.build_all()`) | C → todos |

Para otro stage, reemplazar `arquifusion-dev-` en `EventBusName` antes de `put-events`.
