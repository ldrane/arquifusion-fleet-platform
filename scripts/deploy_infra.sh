#!/usr/bin/env bash
# Despliega la infraestructura AWS en orden (infra/README.md): bootstrap tfstate -> base -> ingest -> incidents/query -> frontend.
# GCP va aparte (necesita gcloud y gcp_project_id): terraform -chdir=infra/gcp apply -var stage=$STAGE -var gcp_project_id=<id>
#   (sin facturación por defecto: gcp_billing=false; ver infra/gcp/README.md)
# Uso: STAGE=dev scripts/deploy_infra.sh [stack ...]   (sin argumentos = todos los de AWS)
# Extra por stack: TF_ARGS_<stack>="-var ack_timeout_s=120"  ·  AUTO_APPROVE=1 para no confirmar cada apply.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${STAGE:?Falta STAGE}"
REGION="${AWS_REGION:-us-east-1}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="arquifusion-tfstate-$ACCOUNT"
STACKS=("${@:-base ingest incidents query frontend}")
read -r -a STACKS <<<"${STACKS[*]}"

log() { printf '\n[deploy %s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }

# 1) Bucket de tfstate (idempotente) + backend.hcl
if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  log "Creando bucket de tfstate $BUCKET"
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" >/dev/null
  aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
  aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
    BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
fi
printf 'bucket = "%s"\nregion = "%s"\n' "$BUCKET" "$REGION" >"$ROOT/infra/backend.hcl"

# 2) Layers (los stacks los leen de build/)
[[ -f "$ROOT/build/layer-a-common.zip" ]] || "$ROOT/scripts/build_layer.sh"
[[ -f "$ROOT/build/layer-c-gcp.zip" ]] || "$ROOT/scripts/build_query_layer.sh"

# 3) Stacks en orden
APPROVE=(); [[ "${AUTO_APPROVE:-0}" == 1 ]] && APPROVE=(-auto-approve)
for s in "${STACKS[@]}"; do
  log "== $s"
  extra_var="TF_ARGS_${s}"
  terraform -chdir="$ROOT/infra/$s" init -input=false -reconfigure -backend-config=../backend.hcl >/dev/null
  # shellcheck disable=SC2086
  terraform -chdir="$ROOT/infra/$s" apply -input=false -var "stage=$STAGE" ${!extra_var:-} "${APPROVE[@]}"
done

# 4) Tras ingest, base necesita un nuevo deployment del stage v1 para publicar POST /telemetry (infra/base/README.md)
if [[ " ${STACKS[*]} " == *" ingest "* ]]; then
  log "Redeploy del stage v1 (POST /telemetry)"
  terraform -chdir="$ROOT/infra/base" apply -input=false -var "stage=$STAGE" -var "api_redeploy=$(date +%s)" "${APPROVE[@]}"
fi
log "OK. Siguientes: secreto de Gemini, seed.py, cognito_users.py, infra/gcp, smoke_golden_path.sh"
