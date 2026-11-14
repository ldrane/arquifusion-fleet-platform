# Simulador de flota

- **Dueño:** Persona A
- **Qué hace:** genera telemetría de 50-100 máquinas (`excavator`, `mining_truck`, `loader`, `bulldozer`, `drill`) en 3-5 zonas y la envía a `POST /telemetry` en lotes ≤100 con `x-api-key`.
- **Escenarios** (`--scenario`): `normal`, `degradacion`, `falla_subita`, `combustible`, `grupal_zona`, `ociosa`.
- **Historial:** `--history 90d` genera el histórico sintético con fallas etiquetadas para entrenar el modelo.
- **Cubre:** RF-01, requerimientos §5.6.
- **Uso:** `python -m simulator --api-url $API_URL --api-key $API_KEY --scenario degradacion --machine EX-023`
