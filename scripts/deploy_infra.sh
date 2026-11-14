#!/usr/bin/env bash
# Despliega la infraestructura AWS en orden (infra/README.md): bootstrap tfstate -> base -> ingest -> incidents/query.
# frontend no va por defecto: el Learner Lab deniega CloudFront. Front: scripts/deploy_frontend.sh (Firebase Hosting).
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
STACKS=("${@:-base ingest incidents query}")
read -r -a STACKS <<<"${STACKS[*]}"

log() { printf '\n[deploy %s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }

# 0) Learner Lab: una SCP deniega s3:GetBucketObjectLockConfiguration y el proveedor AWS la llama en cada
#    lectura de `resource "aws_s3_bucket"` -> el apply siempre falla. Los buckets se crean con
#    infra/modules/lab_s3_bucket. Cortamos aquí antes de dejar un apply a medias.
if grep -rnE '^\s*resource\s+"aws_s3_bucket"\s' "$ROOT/infra" --include='*.tf' --exclude-dir=.terraform; then
  log "ERROR: hay 'resource \"aws_s3_bucket\"' en infra/ (arriba). En Learner Lab usa module \"../modules/lab_s3_bucket\"."
  exit 1
fi

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
  # Migración: si un apply anterior dejó aws_s3_bucket.* en el estado, se "olvida" (el bucket NO se borra);
  # el módulo lab_s3_bucket lo detecta como existente y lo reutiliza. Un `removed {}` no sirve: Terraform
  # refresca el recurso antes de olvidarlo y vuelve a chocar con la SCP.
  legacy="$(terraform -chdir="$ROOT/infra/$s" state list 2>/dev/null | grep -E '^aws_s3_bucket\.[^.]+$' || true)"
  if [[ -n "$legacy" ]]; then
    log "Quitando del estado (sin borrar en AWS): $(echo $legacy)"
    # shellcheck disable=SC2086
    terraform -chdir="$ROOT/infra/$s" state rm $legacy >/dev/null
  fi
  # ingest: las Lambdas procesar/retrain son imágenes de ECR. Se crea primero el repo y se suben las imágenes
  # (docker o podman). SKIP_IMAGES=1 para no reconstruirlas si ya están.
  if [[ "$s" == ingest && "${SKIP_IMAGES:-0}" != 1 ]]; then
    terraform -chdir="$ROOT/infra/ingest" apply -input=false -var "stage=$STAGE" -target=aws_ecr_repository.ml \
      ${!extra_var:-} -auto-approve >/dev/null
    REPO="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/arquifusion-$STAGE-ml"
    TAG="${IMAGE_TAG:-latest}"
    log "Imágenes ECR -> $REPO (procesar-$TAG, retrain-$TAG)"
    aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${REPO%%/*}" >/dev/null
    docker build -q --platform linux/amd64 --provenance=false -f "$ROOT/services/ingest/procesar/Dockerfile" \
      -t "$REPO:procesar-$TAG" "$ROOT" >/dev/null
    docker build -q --platform linux/amd64 --provenance=false -f "$ROOT/services/analytics/retrain/Dockerfile" \
      -t "$REPO:retrain-$TAG" "$ROOT" >/dev/null
    docker push -q "$REPO:procesar-$TAG" >/dev/null
    docker push -q "$REPO:retrain-$TAG" >/dev/null
  fi
  # shellcheck disable=SC2086
  terraform -chdir="$ROOT/infra/$s" apply -input=false -var "stage=$STAGE" ${!extra_var:-} "${APPROVE[@]}"
done

# 4) Tras ingest, base necesita un nuevo deployment del stage v1 para publicar POST /telemetry (infra/base/README.md)
if [[ " ${STACKS[*]} " == *" ingest "* ]]; then
  log "Redeploy del stage v1 (POST /telemetry)"
  terraform -chdir="$ROOT/infra/base" apply -input=false -var "stage=$STAGE" -var "api_redeploy=$(date +%s)" "${APPROVE[@]}"
fi
# 5) API key de Gemini (RF-02.6): desde $GEMINI_API_KEY o .env.deploy (ignorado por git). Idempotente.
[[ -z "${GEMINI_API_KEY:-}" && -f "$ROOT/.env.deploy" ]] && GEMINI_API_KEY="$(sed -n 's/^GEMINI_API_KEY=//p' "$ROOT/.env.deploy")"
if [[ " ${STACKS[*]} " == *" ingest "* && -n "${GEMINI_API_KEY:-}" ]]; then
  log "Cargando API key de Gemini en arquifusion/$STAGE/gemini/api-key"
  aws secretsmanager put-secret-value --region "$REGION" --secret-id "arquifusion/$STAGE/gemini/api-key" \
    --secret-string "$GEMINI_API_KEY" >/dev/null
fi
log "OK. Siguientes: seed.py, cognito_users.py, deploy_frontend.sh, infra/gcp, smoke_golden_path.sh"
