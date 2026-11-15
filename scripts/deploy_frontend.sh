#!/usr/bin/env bash
# Publica la consola web (RF-15). Dos destinos:
#   HOSTING=firebase (por defecto): Firebase Hosting del proyecto GCP (frontend/.firebaserc). HTTPS gratis, sin costo
#     fijo. Es el camino en AWS Academy: el Learner Lab deniega CloudFront (OAC, OAI, ListCachePolicies), así que
#     infra/frontend no se puede aplicar ahí. Requiere `npx firebase-tools login` una vez.
#   HOSTING=aws: stack infra/frontend (S3 privado + CloudFront). Solo en cuentas que permitan CloudFront.
# Uso: STAGE=dev scripts/deploy_frontend.sh   (desde la raíz; requiere frontend/.env.local con los outputs reales)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${STAGE:?Falta STAGE}"
HOSTING="${HOSTING:-firebase}"
[[ -f "$ROOT/frontend/.env.local" ]] || echo "AVISO: sin frontend/.env.local el front se publica en MODO DEMO" >&2
(cd "$ROOT/frontend" && npm run build)

if [[ "$HOSTING" == firebase ]]; then
  (cd "$ROOT/frontend" && npx --yes firebase-tools@15.36.0 deploy --only hosting --non-interactive)
  exit 0
fi

TF="terraform -chdir=$ROOT/infra/frontend"
BUCKET="$($TF output -raw bucket)"
DIST="$($TF output -raw distribution_id)"
# Assets con hash: caché larga. index.html: sin caché para que cada deploy se vea al instante.
aws s3 sync "$ROOT/frontend/dist" "s3://$BUCKET" --delete --exclude index.html \
  --cache-control "public,max-age=31536000,immutable"
aws s3 cp "$ROOT/frontend/dist/index.html" "s3://$BUCKET/index.html" --cache-control "no-cache"
aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/index.html" "/" >/dev/null
echo "OK: $($TF output -raw url)"
