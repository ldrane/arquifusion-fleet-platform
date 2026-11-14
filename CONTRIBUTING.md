# Cómo contribuir

Plan completo y responsables: [`docs/division-trabajo-backend.md`](docs/division-trabajo-backend.md).

## Reglas de oro
1. **Contract-first.** Si cambia un endpoint, evento o campo: PR a `contracts/` → aprobación de quien lo consume → código.
2. **Golden path primero.** Nadie empieza features de H3 hasta que el flujo simulador → incidente cerrado funcione.
3. **Nada a mano en la consola** que no quede en Terraform antes del merge.

## Ramas y commits
- `main` siempre desplegable. Ramas: `feat/<a|b|c>-RF-xx-descripcion` (ej. `feat/b-RF-06-scoring`).
- Commits convencionales con ID de requerimiento: `feat(incidents): scoring de técnicos por ETA (RF-06.2)`.
- PRs < 300 líneas, review de 1 persona. Si tocan `contracts/` o `services/shared/`: review de las 3.

## Código
- Python 3.12. Cada servicio: `handler.py` (delgado) + `service.py` (lógica pura) + `tests/` + `README.md`.
- Usa siempre `arquifusion_shared` para respuestas, errores, logger y RBAC.
- Clientes boto3 fuera del handler. Secretos en Secrets Manager / SSM, nunca en código ni variables de entorno.
- Idempotencia en todo consumidor (escrituras condicionales). `correlation_id` en logs, eventos, Pub/Sub y Firestore.
- Toda llamada a GCP con timeout y fallback. La IA nunca bloquea la Step Function.

## Entornos (AWS Academy)
- Cuenta de integración (`stage=dev`): solo se despliega desde `main`. Ahí se hace la demo.
- Cada persona prueba en su propio Learner Lab con `stage=<inicial>`.

## Definition of Done
- [ ] Desplegado por Terraform en la cuenta de integración
- [ ] Respeta el contrato (test contra fixture en verde)
- [ ] Logs con `correlation_id` y errores con el envoltorio estándar
- [ ] README del servicio con el RF que cubre
- [ ] `scripts/smoke_golden_path.sh` sigue pasando (desde H2)

## Setup local
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e services/shared
pytest
```
