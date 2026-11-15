#!/usr/bin/env bash
# Construye build/layer-a-common.zip con arquifusion_shared + arquifusion_ml + sus dependencias.
# Uso: scripts/build_layer.sh   (desde la raíz del repo)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/build/layer-a-common"
ZIP="$ROOT/build/layer-a-common.zip"
# F-39: solo se salta si el zip es más nuevo que todo el código de services/shared y services/ml
if [[ -f "$ZIP" && -z "$(find "$ROOT/services/shared" "$ROOT/services/ml" -type f \( -name '*.py' -o -name '*.toml' -o -name '*.txt' -o -name '*.json' -o -name '*.cfg' \) -newer "$ZIP" -not -path '*/__pycache__/*' -print -quit)" ]]; then
  echo "OK (sin cambios): build/layer-a-common.zip"; exit 0
fi
mkdir -p "$ROOT/build"
rm -f "$ZIP"
rm -rf "$OUT" && mkdir -p "$OUT/python"
pip install --quiet --target "$OUT/python" "$ROOT/services/shared" "$ROOT/services/ml"
(cd "$OUT" && zip -qr "$ROOT/build/layer-a-common.zip" python)
echo "OK: build/layer-a-common.zip"
