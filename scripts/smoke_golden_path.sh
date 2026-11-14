#!/usr/bin/env bash
# Smoke E2E del golden path. Requiere: API_URL, API_KEY, JWT_TECNICO.
set -euo pipefail
: "${API_URL:?}" "${API_KEY:?}" "${JWT_TECNICO:?}"

# 1. Inyectar degradación en EX-023
# python -m simulator --api-url "$API_URL" --api-key "$API_KEY" --scenario degradacion --machine EX-023
# 2. Esperar incidente abierto (GET /v1/incidents?machine_id=EX-023&status=assigned)
# 3. POST /v1/incidents/{id}/ack
# 4. POST /v1/incidents/{id}/resolve
# 5. Verificar status=closed y resumen IA
echo "TODO: implementar smoke del golden path" >&2
exit 1
