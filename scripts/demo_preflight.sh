#!/usr/bin/env bash
# Preflight de la demo (TAREA-18): solo lee. Sale con != 0 si algo crítico no está listo; imprime en verde/rojo.
# No imprime secretos (JWT, tokens, contraseñas): solo su presencia y estado.
#
# Uso: STAGE=dev scripts/demo_preflight.sh
#   Variables: STAGE (requerido), AWS_REGION (def. us-east-1), PYTHON (def. python3).
#   Toma DEMO_PASSWORD de $DEMO_PASSWORD o de .env.deploy (igual que el resto de scripts).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${STAGE:?Falta STAGE (ej. STAGE=dev scripts/demo_preflight.sh)}"
REGION="${AWS_REGION:-us-east-1}"
PYTHON="${PYTHON:-python3}"
PREFIX="arquifusion-${STAGE}"
SSM="/arquifusion/${STAGE}"

FAIL=0
BODY_FILE="$(mktemp)"
trap 'rm -f "$BODY_FILE"' EXIT

ok()   { printf '  \033[32m✓\033[0m %s\n' "$1"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$1"; FAIL=1; }
warn() { printf '  \033[33m•\033[0m %s\n' "$1"; }
step() { printf '\n[%s]\n' "$1"; }

env_value() { # key -> valor de .env.deploy (nunca se imprime)
  local file="$ROOT/.env.deploy"
  [[ -f "$file" ]] || return 0
  sed -n "s/^$1=//p" "$file" | tail -1 | tr -d '"'\''\r'
}

ssm_get() { aws ssm get-parameter --region "$REGION" --name "$1" --query Parameter.Value --output text 2>/dev/null; }

json_field() { # <json en stdin> <campo>
  "$PYTHON" -c 'import json,sys; print((json.load(sys.stdin) or {}).get(sys.argv[1], ""))' "$1" 2>/dev/null
}

# 1) Credenciales del lab -----------------------------------------------------
step "1/7 credenciales del lab"
if ACCOUNT="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)" && [[ -n "$ACCOUNT" ]]; then
  ok "aws sts get-caller-identity → cuenta ${ACCOUNT}"
else
  bad "aws sts get-caller-identity (¿sesión del lab vencida o falta AWS_REGION?)"
fi

# 2) Pulso LIVE (AWS real) ----------------------------------------------------
step "2/7 GET /system/pulse con JWT de un usuario demo"
API_URL="$(ssm_get "$SSM/api/url")"
CLIENT_ID="$(ssm_get "$SSM/cognito/client_id")"
DEMO_PASSWORD="${DEMO_PASSWORD:-$(env_value DEMO_PASSWORD)}"
if [[ -z "$API_URL" || -z "$CLIENT_ID" ]]; then
  bad "faltan parámetros SSM ($SSM/api/url, $SSM/cognito/client_id): ¿aplicaste infra/base?"
elif [[ -z "$DEMO_PASSWORD" ]]; then
  bad "falta DEMO_PASSWORD (export o .env.deploy)"
else
  TOKEN="$(AWS_DEFAULT_REGION="$REGION" aws cognito-idp initiate-auth \
    --client-id "$CLIENT_ID" --auth-flow USER_PASSWORD_AUTH \
    --auth-parameters "USERNAME=u-op-01,PASSWORD=$DEMO_PASSWORD" \
    --query 'AuthenticationResult.IdToken' --output text 2>/dev/null)"
  if [[ -z "$TOKEN" || "$TOKEN" == "None" ]]; then
    bad "Cognito no devolvió token para u-op-01 (¿corriste scripts/cognito_users.py?)"
  else
    CODE="$(curl -s -o "$BODY_FILE" -w '%{http_code}' -H "Authorization: Bearer $TOKEN" "$API_URL/system/pulse")"
    MODE="$(json_field mode <"$BODY_FILE")"
    if [[ "$CODE" == "200" && "$MODE" == "live" ]]; then
      ok "GET /system/pulse → 200 (mode=live); badge del front en verde"
    else
      bad "GET /system/pulse → HTTP $CODE (mode='${MODE:-?}'); se espera 200 con mode=live"
    fi
  fi
fi

# 3) Últimas ejecuciones de las Step Functions --------------------------------
step "3/7 últimas ejecuciones de GestionIncidente y AnalisisDiario"
for sm in gestion-incidente analisis-diario; do
  ARN="$(aws stepfunctions list-state-machines --region "$REGION" \
    --query "stateMachines[?name=='${PREFIX}-${sm}'].stateMachineArn | [0]" --output text 2>/dev/null)"
  if [[ -z "$ARN" || "$ARN" == "None" ]]; then
    bad "no encuentro la state machine ${PREFIX}-${sm} (¿aplicaste el stack?)"
    continue
  fi
  LAST="$(aws stepfunctions list-executions --region "$REGION" --state-machine-arn "$ARN" --max-results 1 \
    --query 'executions[0].[status,startDate]' --output text 2>/dev/null)"
  [[ -n "$LAST" && "$LAST" != "None" ]] && ok "${PREFIX}-${sm}: ${LAST}" || warn "${PREFIX}-${sm}: sin ejecuciones todavía"
done

# 4) IA (Gemini) --------------------------------------------------------------
step "4/7 sonda de la IA (AI Studio / Vertex express)"
if "$PYTHON" "$ROOT/scripts/check_gemini.py" >"$BODY_FILE" 2>&1; then
  tail -4 "$BODY_FILE" | sed 's/^/  /'
  ok "la IA responde"
else
  tail -4 "$BODY_FILE" | sed 's/^/  /'
  bad "la IA no responde (revisa GEMINI_API_KEY)"
fi

# 5) Telegram (webhook) -------------------------------------------------------
step "5/7 webhook de Telegram"
TG_SECRET="$(aws secretsmanager get-secret-value --region "$REGION" --secret-id "$PREFIX/telegram" \
  --query SecretString --output text 2>/dev/null || true)"
TG_TOKEN="$(printf '%s' "$TG_SECRET" | json_field bot_token)"
if [[ -z "$TG_TOKEN" ]]; then
  warn "sin token de Telegram en $PREFIX/telegram (notify-telegram no enviará; el resto de la demo no depende de esto)"
else
  INFO="$(curl -s "https://api.telegram.org/bot${TG_TOKEN}/getWebhookInfo")"
  WG_URL="$(printf '%s' "$INFO" | json_field url)"
  WG_PENDING="$(printf '%s' "$INFO" | "$PYTHON" -c 'import json,sys;print(json.load(sys.stdin)["result"].get("pending_update_count",0))' 2>/dev/null)"
  WG_ERR="$(printf '%s' "$INFO" | "$PYTHON" -c 'import json,sys;print(json.load(sys.stdin)["result"].get("last_error_message",""))' 2>/dev/null)"
  if [[ -n "$WG_URL" ]]; then
    ok "getWebhookInfo: url configurada, pending_update_count=$WG_PENDING${WG_ERR:+, último error: $WG_ERR}"
  else
    bad "getWebhookInfo sin URL (corre scripts/telegram_setup.py --set-webhook)"
  fi
fi

# 6) Firestore accesible ------------------------------------------------------
step "6/7 Firestore (Firebase/GCP) accesible con la service account"
PYTHONPATH="$ROOT/services/query/common" "$PYTHON" - "$STAGE" "$REGION" >"$BODY_FILE" 2>&1 <<'PY'
import json, sys
try:
    import boto3
    from query_common import gcp
except Exception as exc:  # noqa: BLE001 (falta boto3/google-auth/urllib3 fuera de la Lambda)
    print(f"dependencias no disponibles aquí ({exc}); es normal fuera del venv/la Lambda")
    raise SystemExit(3)
stage, region = sys.argv[1], sys.argv[2]
try:
    secret = boto3.client("secretsmanager", region_name=region).get_secret_value(SecretId=f"arquifusion/{stage}/gcp/service-account")
    sa = json.loads(secret["SecretString"])
    transport = gcp.authorized_transport(sa)
    url = f"{gcp.FIRESTORE_API}/projects/{sa['project_id']}/databases/(default)/documents/machines?pageSize=1"
    status, body = transport("GET", url, {})
    docs = len(body.get("documents", [])) if isinstance(body, dict) else 0
    print(f"Firestore machines → HTTP {status} ({docs} doc de muestra)")
    raise SystemExit(0 if status == 200 else 1)
except ImportError as exc:
    print(f"falta google-auth ({exc}); instálalo o corre esta verificación en la Lambda")
    raise SystemExit(3)
PY
FS_RC=$?
sed 's/^/  /' "$BODY_FILE"
case "$FS_RC" in
  0) ok "Firestore accesible" ;;
  3) warn "no verificable aquí (sin google-auth): el resto de la demo no depende de esto" ;;
  *) bad "Firestore no responde 200" ;;
esac

# 7) Simulador serverless -----------------------------------------------------
step "7/7 estado del simulador serverless"
SIM_STATE="$(ssm_get "$SSM/sim/state")"
if [[ -z "$SIM_STATE" ]]; then
  bad "falta $SSM/sim/state (¿aplicaste infra/ingest?)"
else
  SIM_ON="$(printf '%s' "$SIM_STATE" | json_field enabled)"
  if [[ "$SIM_ON" == "True" || "$SIM_ON" == "true" ]]; then
    ok "simulador ENCENDIDO: $(printf '%s' "$SIM_STATE" | head -c 160)"
  else
    warn "simulador apagado (enciéndelo desde la consola o con simStart antes del pitch)"
  fi
fi

printf '\n'
if [[ "$FAIL" == "0" ]]; then
  printf '\033[32mPreflight OK\033[0m (los avisos • no bloquean la demo)\n'
else
  printf '\033[31mPreflight con fallas\033[0m: revisa los ✗ de arriba\n'
fi
exit "$FAIL"
