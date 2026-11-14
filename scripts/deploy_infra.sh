#!/usr/bin/env bash
# Despliega la infraestructura AWS en orden (infra/README.md): bootstrap tfstate -> base -> ingest -> incidents/query -> frontend.
# GCP va aparte (necesita gcloud y gcp_project_id): terraform -chdir=infra/gcp apply -var stage=$STAGE -var gcp_project_id=<id>
#   (sin facturación por defecto: gcp_billing=false; ver infra/gcp/README.md)
# Uso: STAGE=dev scripts/deploy_infra.sh [stack ...]
#   Sin argumentos = base ingest incidents query (SIN frontend: CloudFront+OAC no está garantizado en Learner Lab;
#   despliégalo aparte con `scripts/deploy_infra.sh frontend` o scripts/deploy_frontend.sh).
#   Orden real: base -> ingest (con imágenes ECR) -> redeploy stage v1 -> incidents -> query.
# Requiere docker (build/push de las imágenes de procesar y retrain) al desplegar `ingest`. IMAGE_TAG (def. latest).
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
#    Los scripts se saltan solos si el zip está al día respecto a su código fuente (F-39).
"$ROOT/scripts/build_layer.sh"
"$ROOT/scripts/build_query_layer.sh"
IMAGE_TAG="${IMAGE_TAG:-latest}"

# F-01: crea el repo ECR (apply -target), hace login y construye/sube procesar y retrain (linux/amd64).
ecr_images() {
  command -v docker >/dev/null || { log "ERROR: falta docker; es necesario para construir las imágenes de procesar/retrain (ver docs/RUNBOOK-DEPLOY.md)."; exit 1; }
  docker info >/dev/null 2>&1 || { log "ERROR: el daemon de docker no responde. Inícialo y reintenta."; exit 1; }
  log "ECR: creando repositorio (apply -target=aws_ecr_repository.ml)"
  # shellcheck disable=SC2086
  terraform -chdir="$ROOT/infra/ingest" apply -input=false -var "stage=$STAGE" -var "image_tag=$IMAGE_TAG" ${TF_ARGS_ingest:-} \
    -target=aws_ecr_repository.ml "${APPROVE[@]}"
  local repo
  repo="$(terraform -chdir="$ROOT/infra/ingest" output -raw ecr_repository_url)"
  aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${repo%%/*}"
  local pair name dockerfile
  for pair in "procesar:services/ingest/procesar/Dockerfile" "retrain:services/analytics/retrain/Dockerfile"; do
    name="${pair%%:*}"; dockerfile="${pair#*:}"
    log "docker build/push $repo:$name-$IMAGE_TAG"
    # Contexto = raíz del repo (los Dockerfile copian services/shared, services/ml, ...)
    docker build --platform linux/amd64 -f "$ROOT/$dockerfile" -t "$repo:$name-$IMAGE_TAG" "$ROOT"
    docker push "$repo:$name-$IMAGE_TAG"
  done
}

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
  if [[ "$s" == ingest ]]; then
    ecr_images   # F-01: el repo ECR y las imágenes deben existir antes del apply completo (Lambdas package_type=Image)
  fi
  tag_args=(); [[ "$s" == ingest ]] && tag_args=(-var "image_tag=$IMAGE_TAG")
  # shellcheck disable=SC2086
  terraform -chdir="$ROOT/infra/$s" apply -input=false -var "stage=$STAGE" "${tag_args[@]}" ${!extra_var:-} "${APPROVE[@]}"
done

# 4) Tras ingest, base necesita un nuevo deployment del stage v1 para publicar POST /telemetry (infra/base/README.md)
if [[ " ${STACKS[*]} " == *" ingest "* ]]; then
  log "Redeploy del stage v1 (POST /telemetry)"
  # shellcheck disable=SC2086
  terraform -chdir="$ROOT/infra/base" apply -input=false -var "stage=$STAGE" ${TF_ARGS_base:-} -var "api_redeploy=$(date +%s)" "${APPROVE[@]}"
fi
# 5) API key de Gemini (RF-02.6): desde $GEMINI_API_KEY o .env.deploy (ignorado por git). Idempotente.
[[ -z "${GEMINI_API_KEY:-}" && -f "$ROOT/.env.deploy" ]] && GEMINI_API_KEY="$(sed -n 's/^GEMINI_API_KEY=//p' "$ROOT/.env.deploy")"
if [[ " ${STACKS[*]} " == *" ingest "* && -n "${GEMINI_API_KEY:-}" ]]; then
  log "Cargando API key de Gemini en arquifusion/$STAGE/gemini/api-key"
  aws secretsmanager put-secret-value --region "$REGION" --secret-id "arquifusion/$STAGE/gemini/api-key" \
    --secret-string "$GEMINI_API_KEY" >/dev/null
fi
log "OK. Siguientes: seed.py, cognito_users.py, infra/gcp, smoke_golden_path.sh"
