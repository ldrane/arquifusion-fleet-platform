# Fixtures de contrato

Ejemplos canónicos de cada interfaz. **Productor y consumidor prueban contra el mismo archivo.**
Si cambia un contrato: primero `contratos.md` / `openapi.yaml`, luego el fixture y recién después el código.

| Carpeta | Interfaz | Productor → Consumidor |
|---|---|---|
| `events/` | EventBridge `fleet-events` (formato `aws events put-events --entries file://...`) | A/B → B |
| `pubsub/` | Mensaje `notificaciones` | B (`notificar`) → B (Cloud Function) |
| `ia/` | Invocación `ia-gemini` | B (SFN) → A |
| `internal/` | `scoring-tecnicos`, `correlacion-zona` | B (SFN) → B |
| `api/` | Cuerpos REST de ejemplo | Simulador / front → API |

> Revisar que los nombres de campo de `api/telemetry_batch.json` coincidan con el schema de `openapi.yaml` (fuente de verdad).
