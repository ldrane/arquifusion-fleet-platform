#!/usr/bin/env bash
# Publica la consola web (RF-15) en el stack infra/frontend: build de Vite + s3 sync + invalidación de CloudFront.
# Uso: STAGE=dev scripts/deploy_frontend.sh   (desde la raíz; requiere frontend/.env.local con los outputs reales)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${STAGE:?Falta STAGE}"
TF="terraform -chdir=$ROOT/infra/frontend"
BUCKET="$($TF output -raw bucket)"
DIST="$($TF output -raw distribution_id)"
[[ -f "$ROOT/frontend/.env.local" ]] || echo "AVISO: sin frontend/.env.local el front se publica en MODO DEMO" >&2
(cd "$ROOT/frontend" && npm run build)
# Assets con hash: caché larga. index.html: sin caché para que cada deploy se vea al instante.
aws s3 sync "$ROOT/frontend/dist" "s3://$BUCKET" --delete --exclude index.html \
  --cache-control "public,max-age=31536000,immutable"
aws s3 cp "$ROOT/frontend/dist/index.html" "s3://$BUCKET/index.html" --cache-control "no-cache"
aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/index.html" "/" >/dev/null
echo "OK: $($TF output -raw url)"
