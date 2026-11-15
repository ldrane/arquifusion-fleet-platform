#!/usr/bin/env bash
# Guardia anti-regresión local (TAREA-04): sintaxis, JSON, lint, tests y validación de Terraform.
# Uso: scripts/check_all.sh [--fast]
#   --fast: solo sintaxis Python (fase 1) y JSON (fase 2); lo usa deploy_infra.sh antes de tocar AWS.
# Variables: PYTHON (def. python3), SKIP_TERRAFORM=1 para omitir la fase 6.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
FAST=0
[[ "${1:-}" == "--fast" ]] && FAST=1
PY="${PYTHON:-python3}"
PYTHONPATH_CHECKS="services/shared:services/ml:services/analytics/common:services/query/common"

log() { printf '\n[check_all] %s\n' "$*" >&2; }

log "1/6 compilando Python (services gcp simulator scripts)"
"$PY" -m compileall -q services gcp simulator scripts

log "2/6 validando JSON"
"$PY" - <<'PY'
import json
import re
import sys
from pathlib import Path

root = Path(".")
bad = []
for path in root.rglob("*.json"):
    if "node_modules" in path.parts or ".terraform" in path.parts:
        continue
    text = path.read_text(encoding="utf-8")
    if path.name.endswith(".asl.json"):
        text = re.sub(r"\$\{\w+\}", "1", text)
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        bad.append(f"{path}: {exc}")
if bad:
    print("\n".join(bad), file=sys.stderr)
    raise SystemExit(1)
print(f"JSON OK ({len(list(root.rglob('*.json')))} archivos revisados)", file=sys.stderr)
PY

if [[ "$FAST" == 1 ]]; then
  log "modo --fast: fin"
  exit 0
fi

log "3/6 ruff check ."
"$PY" -m ruff check .

log "4/6 pytest"
PYTHONPATH="$PYTHONPATH_CHECKS" "$PY" -m pytest -q services gcp simulator scripts/tests

if [[ -d frontend/node_modules ]]; then
  log "5/6 frontend (tsc, vitest, vite build)"
  (cd frontend && npx tsc --noEmit && npx vitest run && npx vite build)
else
  log "5/6 frontend omitido (no hay frontend/node_modules; ejecuta pnpm install)"
fi

if [[ "${SKIP_TERRAFORM:-0}" != 1 ]] && command -v terraform >/dev/null 2>&1; then
  log "6/6 terraform validate"
  for stack in base ingest incidents query gcp; do
    [[ -d "infra/$stack" ]] || continue
    terraform -chdir="infra/$stack" init -backend=false -input=false >/dev/null
    terraform -chdir="infra/$stack" validate
  done
else
  log "6/6 terraform omitido"
fi

log "OK"
