#!/usr/bin/env bash
# Publica la consola web (RF-15) en el stack infra/frontend: build de Vite + s3 sync + invalidación de CloudFront.
# Uso: STAGE=dev scripts/deploy_frontend.sh   (desde la raíz; VITE_* desde entorno, frontend/.env.local o outputs de infra/base)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${STAGE:?Falta STAGE}"
TF="terraform -chdir=$ROOT/infra/frontend"
BUCKET="$($TF output -raw bucket)"
DIST="$($TF output -raw distribution_id)"

# --- Variables VITE_* del build (se hornean en el bundle; son PÚBLICAS, pero no se imprimen valores) ---
# Precedencia (Vite): variables de entorno del shell > frontend/.env.local. Si faltan VITE_API_URL / VITE_COGNITO_CLIENT_ID
# se intentan leer de los outputs de infra/base (api_url, cognito_client_id). Firebase solo viene de entorno o .env.local.
ENV_LOCAL="$ROOT/frontend/.env.local"
has_var() { # ¿VITE_X está definida y no vacía en el entorno o en .env.local?
  [[ -n "${!1:-}" ]] && return 0
  [[ -f "$ENV_LOCAL" ]] && grep -Eq "^[[:space:]]*$1=[^[:space:]]+" "$ENV_LOCAL"
}
if ! has_var VITE_API_URL; then
  if v="$(terraform -chdir="$ROOT/infra/base" output -raw api_url 2>/dev/null)" && [[ -n "$v" ]]; then
    export VITE_API_URL="$v"; echo "VITE_API_URL tomada de infra/base (output api_url)" >&2
  fi
fi
if ! has_var VITE_COGNITO_CLIENT_ID; then
  if v="$(terraform -chdir="$ROOT/infra/base" output -raw cognito_client_id 2>/dev/null)" && [[ -n "$v" ]]; then
    export VITE_COGNITO_CLIENT_ID="$v"; echo "VITE_COGNITO_CLIENT_ID tomada de infra/base (output cognito_client_id)" >&2
  fi
fi
unset v
if [[ "${VITE_FORCE_DEMO:-}" == "true" ]]; then
  echo "AVISO: VITE_FORCE_DEMO=true: el front se publica en MODO DEMO" >&2
elif ! has_var VITE_API_URL; then
  echo "ERROR: falta VITE_API_URL y no es modo demo. Defínela (entorno o frontend/.env.local) o exporta VITE_FORCE_DEMO=true para publicar en demo a propósito." >&2
  exit 1
else
  missing=()
  for n in VITE_COGNITO_CLIENT_ID VITE_FIREBASE_API_KEY VITE_FIREBASE_PROJECT_ID VITE_FIREBASE_APP_ID VITE_FIREBASE_AUTH_DOMAIN; do
    has_var "$n" || missing+=("$n")
  done
  if ((${#missing[@]})); then
    echo "AVISO: faltan ${missing[*]} (sin VITE_FIREBASE_API_KEY/PROJECT_ID el chat queda deshabilitado; sin VITE_COGNITO_CLIENT_ID no hay login real)" >&2
  fi
  export VITE_FORCE_DEMO="${VITE_FORCE_DEMO:-false}"
fi
(cd "$ROOT/frontend" && npm run build)
# Assets con hash: caché larga. index.html: sin caché para que cada deploy se vea al instante.
aws s3 sync "$ROOT/frontend/dist" "s3://$BUCKET" --delete --exclude index.html \
  --cache-control "public,max-age=31536000,immutable"
aws s3 cp "$ROOT/frontend/dist/index.html" "s3://$BUCKET/index.html" --cache-control "no-cache"
aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/index.html" "/" >/dev/null
echo "OK: $($TF output -raw url)"
