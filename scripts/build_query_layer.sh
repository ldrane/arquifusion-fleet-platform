#!/usr/bin/env bash
# Construye build/layer-c-gcp.zip (Persona C): google-auth para api_lectura y replicar (contratos.md §5).
# Wheels manylinux para python3.12 x86_64 (igual que las Lambdas). Correr ANTES de `terraform apply` en infra/query.
# Uso: scripts/build_query_layer.sh   (desde la raíz del repo)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/build/layer-c-gcp"
ZIP="$ROOT/build/layer-c-gcp.zip"
# F-39: solo se salta si el zip es más nuevo que los requirements y este script
if [[ -f "$ZIP" && "$ZIP" -nt "$ROOT/services/query/common/requirements.txt" && "$ZIP" -nt "$0" ]]; then
  echo "OK (sin cambios): build/layer-c-gcp.zip"; exit 0
fi
rm -rf "$OUT" "$ROOT/build/layer-c-gcp.zip" && mkdir -p "$OUT/python"
pip install --quiet --target "$OUT/python" \
  --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --only-binary=:all: \
  -r "$ROOT/services/query/common/requirements.txt"
# urllib3 ya viene con boto3 en el runtime; no se duplica si pip lo trajo como dependencia transitiva.
rm -rf "$OUT/python/urllib3" "$OUT/python"/urllib3-*.dist-info
find "$OUT/python" -name '__pycache__' -type d -prune -exec rm -rf {} +
(cd "$OUT" && zip -qr "$ROOT/build/layer-c-gcp.zip" python)
echo "OK: build/layer-c-gcp.zip ($(du -h "$ROOT/build/layer-c-gcp.zip" | cut -f1))"
