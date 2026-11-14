#!/usr/bin/env bash
# Construye build/layer-a-common.zip con arquifusion_shared + arquifusion_ml + sus dependencias.
# Uso: scripts/build_layer.sh   (desde la raíz del repo)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/build/layer-a-common"
rm -rf "$OUT" && mkdir -p "$OUT/python"
pip install --quiet --target "$OUT/python" "$ROOT/services/shared" "$ROOT/services/ml"
(cd "$OUT" && zip -qr "$ROOT/build/layer-a-common.zip" python)
echo "OK: build/layer-a-common.zip"
