"""notify_push (RF-10.2, MH-MC-02): push FCM desde AWS cuando GCP no tiene facturación (sin Cloud Functions).

Reemplaza a la Cloud Function `notify-push` con la MISMA lógica (`notify_bridge.handle_notification`,
copiado de gcp/functions/notify_bridge/main.py en el zip). Dos entradas:

- **Pub/Sub push** (por defecto): suscripción push del topic `notificaciones` → `POST /bridge/push` (API Gateway,
  sin authorizer). Se valida el token OIDC que firma Google: `iss` de Google, `aud == PUSH_AUDIENCE` y
  `email == pubsub-push@<project>.iam.gserviceaccount.com` (infra/gcp/notify.tf). Responde 2xx para hacer ack.
- **Invocación directa** (`PUSH_MODE=direct` en notificar, plan B si la suscripción push no se puede crear):
  `{"notification": {...}, "attributes": {...}}`.

Un push que falla no se reintenta (igual que `RETRY_POLICY_DO_NOT_RETRY` del diseño original): evita duplicados.
"""

import base64
import json
import logging
import time

import notify_bridge

log = logging.getLogger("notify_push")

GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
DEFAULT_AUDIENCE = "arquifusion-notify-push"
CLOCK_SKEW_S = 60


class Unauthorized(Exception):
    pass


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def verify_oidc(token: str, *, audience: str, email: str, keys: dict, verify_rs256, now: float | None = None) -> dict:
    """Valida el JWT OIDC de Pub/Sub. `keys` = {kid: (n, e)} de los certificados de Google."""
    try:
        header_b64, claims_b64, sig_b64 = token.split(".")
        header = json.loads(_b64url_decode(header_b64))
        claims = json.loads(_b64url_decode(claims_b64))
        signature = _b64url_decode(sig_b64)
    except (ValueError, TypeError) as exc:
        raise Unauthorized("token mal formado") from exc
    if header.get("alg") != "RS256" or header.get("kid") not in keys:
        raise Unauthorized("algoritmo o kid desconocido")
    n, e = keys[header["kid"]]
    if not verify_rs256(f"{header_b64}.{claims_b64}".encode(), signature, n, e):
        raise Unauthorized("firma inválida")
    now = time.time() if now is None else now
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise Unauthorized("issuer inválido")
    if claims.get("aud") != audience:
        raise Unauthorized("audience inválida")
    if claims.get("email") != email or claims.get("email_verified") is not True:
        raise Unauthorized("service account inválida")
    if float(claims.get("exp", 0)) + CLOCK_SKEW_S < now:
        raise Unauthorized("token vencido")
    return claims


def parse_jwks(jwks: dict) -> dict:
    """JWKS de Google → {kid: (n, e)}."""
    out = {}
    for k in jwks.get("keys", []):
        if k.get("kty") == "RSA":
            n, e = (int.from_bytes(_b64url_decode(k[x]), "big") for x in ("n", "e"))
            out[k["kid"]] = (n, e)
    return out


def _header(headers: dict | None, name: str) -> str:
    for k, v in (headers or {}).items():
        if k.lower() == name:
            return v or ""
    return ""


def _response(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


class _PushEnvelope:
    """Adapta el cuerpo de la entrega push al `cloud_event` que espera `notify_bridge.decode_pubsub`."""

    def __init__(self, envelope: dict):
        self.data = {"message": envelope.get("message") or {}}


def handle_push(event: dict, deps: dict) -> dict:
    """Entrega push de Pub/Sub vía API Gateway (proxy)."""
    auth = _header(event.get("headers"), "authorization")
    if not auth.lower().startswith("bearer "):
        return _response(401, {"error": {"code": "UNAUTHENTICATED", "message": "Falta el token OIDC"}})
    try:
        deps["verify"](auth[7:].strip())
    except Unauthorized as exc:
        log.warning("Push rechazado: %s", exc)
        return _response(401, {"error": {"code": "UNAUTHENTICATED", "message": "Token OIDC inválido"}})

    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    try:
        notification, attrs = notify_bridge.decode_pubsub(_PushEnvelope(json.loads(raw)))
    except ValueError:
        # Mensaje corrupto: 2xx para que Pub/Sub no lo reintente para siempre
        log.error("Mensaje Pub/Sub inválido")
        return _response(200, {"skipped": "mensaje inválido"})
    return _response(200, deliver(notification, attrs, deps))


def deliver(notification: dict, attrs: dict, deps: dict) -> dict:
    try:
        result = notify_bridge.handle_notification(notification, deps["users"](), deps["send"]())
    except Exception:  # noqa: BLE001 - un push perdido no debe reintentarse (evita duplicados)
        log.exception("No se pudo enviar el push")
        return {"sent": 0, "error": "push_failed", "correlation_id": attrs.get("correlation_id")}
    log.info(json.dumps({"msg": "push enviado", "correlation_id": attrs.get("correlation_id"), **result}))
    return result


def run(event: dict, deps: dict) -> dict:
    if "notification" in event:  # invocación directa desde notificar (PUSH_MODE=direct)
        return deliver(event["notification"], event.get("attributes") or {}, deps)
    return handle_push(event, deps)
