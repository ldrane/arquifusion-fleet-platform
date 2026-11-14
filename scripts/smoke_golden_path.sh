#!/usr/bin/env bash
# Smoke E2E del golden path (#27, RF-01 -> RF-02 -> RF-06 -> RF-11 -> RF-16, contratos.md §6):
#   simulador (degradacion en EX-023) -> procesar -> AnomalyDetected -> GestionIncidente -> asignado a TEC-07
#   -> ack (accept) con JWT del técnico -> in_progress -> resolve -> resumen IA -> closed.
#
# Requiere (desde la raíz del repo, con el venv del simulador):
#   API_URL               URL del stage v1, p. ej. https://abc.execute-api.us-east-1.amazonaws.com/v1 (rutas SIN /v1)
#   SIMULATOR_API_KEY     API key del usage plan ingest (o API_KEY)
#   y el ID token del técnico u-tec-07, de una de dos formas:
#     JWT_TECNICO         ID token ya obtenido, o
#     COGNITO_CLIENT_ID + TEC_PASSWORD (+ TEC_USER, default u-tec-07): se pide con USER_PASSWORD_AUTH (aws cli)
# Opcionales: JWT_MANT (ID token de mantenimiento: reasigna a TEC-07 si la SFN eligió a otro), SPEEDUP (default 600),
#   TIMEOUT_DETECT_S (900), TIMEOUT_STEP_S (240), POLL_S (10), SMOKE_SKIP_SIM=1 (no lanza el simulador), PYTHON.
set -euo pipefail

: "${API_URL:?Falta API_URL (stage v1)}"
API_URL="${API_URL%/}"
API_KEY="${SIMULATOR_API_KEY:-${API_KEY:-}}"
MACHINE="EX-023"
TECH="TEC-07"
SPEEDUP="${SPEEDUP:-600}"
TIMEOUT_DETECT_S="${TIMEOUT_DETECT_S:-900}"
TIMEOUT_STEP_S="${TIMEOUT_STEP_S:-240}"
POLL_S="${POLL_S:-10}"
PYTHON="${PYTHON:-python}"
SIM_PID=""

log() { printf '[smoke %s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
fail() { log "FALLO: $*"; exit 1; }
cleanup() { if [[ -n "$SIM_PID" ]] && kill -0 "$SIM_PID" 2>/dev/null; then kill "$SIM_PID" 2>/dev/null || true; fi; }
trap cleanup EXIT

# jq-less: lee una expresión Python sobre el JSON de stdin (d = cuerpo). Imprime "" si no existe.
jget() { "$PYTHON" -c 'import json,sys
d=json.load(sys.stdin)
try:
    v=eval(sys.argv[1],{"d":d})
except Exception:
    v=None
print("" if v is None else (json.dumps(v) if isinstance(v,(dict,list)) else v))' "$1"; }

# api METHOD PATH [BODY] [TOKEN] -> imprime el cuerpo; falla si HTTP >= 400
api() {
  local method="$1" path="$2" body="${3:-}" token="${4:-$JWT_TECNICO}" out code
  out="$(mktemp)"
  code=$(curl -sS -o "$out" -w '%{http_code}' -X "$method" "$API_URL$path" \
    -H "Authorization: $token" -H "Content-Type: application/json" \
    -H "X-Correlation-Id: smoke-$(date +%s)-$RANDOM" ${body:+--data "$body"})
  if [[ "$code" -ge 400 ]]; then log "$method $path -> HTTP $code: $(cat "$out")"; rm -f "$out"; return 1; fi
  cat "$out"; rm -f "$out"
}

# ---------------------------------------------------------------- 0. JWT del técnico
if [[ -z "${JWT_TECNICO:-}" ]]; then
  : "${COGNITO_CLIENT_ID:?Falta JWT_TECNICO o COGNITO_CLIENT_ID + TEC_PASSWORD}" "${TEC_PASSWORD:?Falta TEC_PASSWORD}"
  JWT_TECNICO=$(aws cognito-idp initiate-auth --auth-flow USER_PASSWORD_AUTH --client-id "$COGNITO_CLIENT_ID" \
    --auth-parameters "USERNAME=${TEC_USER:-u-tec-07},PASSWORD=$TEC_PASSWORD" \
    --query 'AuthenticationResult.IdToken' --output text)
fi

me=$(api GET /me) || fail "GET /me (¿JWT válido? ¿ruta /me cableada por B?)"
[[ "$(jget 'd["data"]["role"]' <<<"$me")" == "tecnico" ]] || fail "el JWT no es de un técnico: $me"
[[ "$(jget 'd["data"]["technician_id"]' <<<"$me")" == "$TECH" ]] || fail "GET /me no trae technician_id=$TECH (custom:technician_id, #8): $me"
log "GET /me OK: u-tec-07 = $TECH"

# ---------------------------------------------------------------- 1. inyectar degradación en EX-023
open_incident() {
  api GET "/incidents?machine_id=$MACHINE&limit=100" | jget '[i for i in d["data"] if i["status"] != "closed"][0]["incident_id"]'
}
INC="$(open_incident || true)"
if [[ -n "$INC" ]]; then
  log "Ya hay un incidente abierto en $MACHINE ($INC): se reutiliza"
elif [[ "${SMOKE_SKIP_SIM:-0}" != "1" ]]; then
  : "${API_KEY:?Falta SIMULATOR_API_KEY (API key de POST /telemetry)}"
  log "Simulador: degradacion en $MACHINE (speedup $SPEEDUP)"
  "$PYTHON" -m simulator stream --api-url "$API_URL" --api-key "$API_KEY" \
    --scenario degradacion --machine "$MACHINE" --speedup "$SPEEDUP" >&2 &
  SIM_PID=$!
fi

# ---------------------------------------------------------------- 2. esperar el incidente asignado
deadline=$((SECONDS + TIMEOUT_DETECT_S))
while :; do
  INC="$(open_incident || true)"
  if [[ -n "$INC" ]]; then
    inc=$(api GET "/incidents/$INC")
    status=$(jget 'd["data"]["status"]' <<<"$inc")
    assignee=$(jget 'd["data"]["assigned_technician_id"]' <<<"$inc")
    log "$INC status=$status técnico=${assignee:-—}"
    [[ "$status" == "assigned" || "$status" == "in_progress" ]] && break
  else
    log "esperando incidente de $MACHINE…"
  fi
  [[ -n "$SIM_PID" ]] && ! kill -0 "$SIM_PID" 2>/dev/null && fail "el simulador terminó antes de tiempo"
  (( SECONDS < deadline )) || fail "no apareció un incidente asignado en ${TIMEOUT_DETECT_S}s"
  sleep "$POLL_S"
done
cleanup; SIM_PID=""   # ya no hace falta más telemetría anómala

if [[ "$status" == "assigned" && "$assignee" != "$TECH" ]]; then
  [[ -n "${JWT_MANT:-}" ]] || fail "la SFN asignó a $assignee (se esperaba $TECH, contratos.md §8.3). Define JWT_MANT para reasignar."
  log "Reasignando $INC a $TECH con mantenimiento"
  api POST "/incidents/$INC/assign" "{\"technician_id\":\"$TECH\",\"reason\":\"smoke golden path\"}" "$JWT_MANT" >/dev/null
fi

wait_status() {  # wait_status <estado> [condición python extra]
  local want="$1" extra="${2:-True}" deadline=$((SECONDS + TIMEOUT_STEP_S)) body s ok
  while :; do
    body=$(api GET "/incidents/$INC")
    s=$(jget 'd["data"]["status"]' <<<"$body")
    ok=$(jget "$extra" <<<"$body")
    if [[ "$s" == "$want" && "$ok" == "True" ]]; then printf '%s' "$body"; return 0; fi
    (( SECONDS < deadline )) || { log "timeout esperando $want (actual: $s)"; return 1; }
    sleep "$POLL_S"
  done
}

# ---------------------------------------------------------------- 3. ack del técnico
if [[ "$status" != "in_progress" ]]; then
  wait_status assigned "d['data']['assigned_technician_id'] == '$TECH'" >/dev/null || fail "$INC no quedó asignado a $TECH"
  ack=$(api POST "/incidents/$INC/ack" '{"decision":"accept"}') || fail "POST /incidents/$INC/ack"
  log "ack OK (pending_transition=$(jget 'd.get("meta",{}).get("pending_transition")' <<<"$ack"))"
  wait_status in_progress >/dev/null || fail "$INC no pasó a in_progress"
fi
log "$INC en atención (in_progress)"

# ---------------------------------------------------------------- 4. resolve y cierre con resumen IA
api POST "/incidents/$INC/resolve" \
  '{"resolution_notes":"Smoke: se reemplazó el kit de rodamientos (CMP-014); temperatura y vibración en rango.","components_replaced":["CMP-014"],"cost_usd":450}' \
  >/dev/null || fail "POST /incidents/$INC/resolve"
log "resolve OK; esperando cierre y resumen IA…"
final=$(wait_status closed "bool(d['data'].get('resolution_summary'))") || fail "$INC no llegó a closed con resolution_summary"

log "OK golden path: $INC closed"
log "  diagnóstico IA: $(jget 'd["data"]["ai_diagnosis"]["probable_cause"]' <<<"$final")"
log "  resumen IA:     $(jget 'd["data"]["resolution_summary"]' <<<"$final")"
log "  downtime_min:   $(jget 'd["data"]["downtime_minutes"]' <<<"$final")"
