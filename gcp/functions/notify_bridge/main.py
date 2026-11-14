"""Cloud Function Gen2 notify_bridge (RF-10.2, RF-16.5, MH-MC-02). Contrato: contratos.md §4 y §5.

- `on_notification`: Pub/Sub `notificaciones` → push FCM a `users/{uid}.fcm_tokens[]`. Si `target.user_id` viene,
  solo a ese usuario; si es null, a todos los `users` con `role == target.role` y `zone in [target.zone, "*"]`.
  Los tokens que FCM rechaza como no registrados se quitan con `arrayRemove`.
- `on_incident_action`: Firestore `incidents/{id}/actions/{event_id}` (creado por el móvil) → `POST /bridge/events`
  en AWS con la API key de Secret Manager. Marca el documento con el resultado (`bridge_status`).

Las dependencias (Firestore, FCM, HTTP, secreto) se inyectan para probar sin GCP; los imports de Google son perezosos.
"""
import base64
import json
import logging
import os
from datetime import UTC, datetime

log = logging.getLogger("notify_bridge")
log.setLevel(logging.INFO)

GLOBAL_ZONE = "*"
BRIDGE_TYPES = {"incident.ack", "incident.resolve", "technician.status"}


# ======================================================================= Pub/Sub → FCM

def decode_pubsub(cloud_event) -> tuple[dict, dict]:
    message = (cloud_event.data or {}).get("message", {})
    raw = base64.b64decode(message.get("data") or b"e30=")  # "{}"
    return json.loads(raw), message.get("attributes") or {}


def recipients(notification: dict, users) -> dict[str, list[str]]:
    """uid → tokens. `users` = repositorio con `get(uid)` y `by_role_zone(role, zones)`."""
    target = notification.get("target") or {}
    if target.get("user_id"):
        doc = users.get(target["user_id"]) or {}
        return {target["user_id"]: list(doc.get("fcm_tokens") or [])}
    zones = [z for z in (target.get("zone"), GLOBAL_ZONE) if z]
    return {uid: list(doc.get("fcm_tokens") or []) for uid, doc in users.by_role_zone(target.get("role"), zones)}


def fcm_data(notification: dict) -> dict:
    """FCM solo acepta strings en `data`."""
    keys = ("notification_id", "event_type", "incident_id", "machine_id", "zone", "severity", "deep_link",
            "correlation_id")
    return {k: str(notification[k]) for k in keys if notification.get(k) is not None}


def handle_notification(notification: dict, users, send) -> dict:
    """`send(tokens, title, body, data, link)` → lista de tokens inválidos."""
    sent, removed = 0, 0
    for uid, tokens in recipients(notification, users).items():
        if not tokens:
            continue
        invalid = send(tokens, notification.get("title") or "", notification.get("body") or "",
                       fcm_data(notification), notification.get("deep_link") or "/")
        sent += len(tokens) - len(invalid)
        if invalid:
            users.remove_tokens(uid, invalid)
            removed += len(invalid)
    return {"sent": sent, "removed_tokens": removed}


class FirestoreUsers:  # pragma: no cover - requiere GCP
    def __init__(self, db):
        self.db = db

    def get(self, uid):
        snap = self.db.collection("users").document(uid).get()
        return snap.to_dict() if snap.exists else None

    def by_role_zone(self, role, zones):
        from google.cloud.firestore_v1.base_query import FieldFilter

        q = (self.db.collection("users").where(filter=FieldFilter("role", "==", role))
             .where(filter=FieldFilter("zone", "in", zones)))
        return [(s.id, s.to_dict()) for s in q.stream()]

    def remove_tokens(self, uid, tokens):
        from google.cloud import firestore

        self.db.collection("users").document(uid).update({"fcm_tokens": firestore.ArrayRemove(tokens)})


def fcm_send(tokens, title, body, data, link):  # pragma: no cover - requiere GCP
    from firebase_admin import messaging

    msg = messaging.MulticastMessage(
        tokens=tokens,
        notification=messaging.Notification(title=title, body=body),
        data=data,
        webpush=messaging.WebpushConfig(fcm_options=messaging.WebpushFCMOptions(link=link)),
    )
    resp = messaging.send_each_for_multicast(msg)
    invalid = []
    for token, r in zip(tokens, resp.responses, strict=False):
        if not r.success and isinstance(r.exception, (messaging.UnregisteredError, messaging.SenderIdMismatchError)):
            invalid.append(token)
        elif not r.success:
            log.warning("FCM falló para un token: %s", r.exception)
    return invalid


# ======================================================================= Firestore actions → AWS /bridge/events

def _iso(value) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value) if value else datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def document_path(cloud_event) -> str:
    """`incidents/INC-1/actions/fs-9f3a1` desde el atributo `document` (o `subject`) del CloudEvent de Firestore."""
    path = cloud_event.get("document") or cloud_event.get("subject") or ""
    return path.removeprefix("documents/")


def build_bridge_event(event_id: str, action: dict, profile: dict | None) -> dict:
    """BridgeEvent del OpenAPI. El actor se completa con `technician_id`/`zone` de `users/{uid}` (claims §2.1)."""
    actor = dict(action.get("actor") or {})
    profile = profile or {}
    if profile.get("role") and actor.get("role") != profile["role"]:
        raise ValueError("El rol del actor no coincide con users/{uid}")
    if profile.get("technician_id"):
        actor["technician_id"] = profile["technician_id"]
    if profile.get("zone") and profile["zone"] != GLOBAL_ZONE:
        actor["zone"] = profile["zone"]
    return {
        "event_id": event_id,
        "type": action.get("type"),
        "incident_id": action.get("incident_id"),
        "actor": actor,
        "data": action.get("data") or {},
        "occurred_at": _iso(action.get("occurred_at")),
        "correlation_id": action.get("correlation_id"),
    }


def handle_action(path: str, store, post, bridge: dict) -> dict:
    """`store`: `get(path)` (acción y `users/{uid}`) y `mark(path, fields)`.
    `post(url, body, api_key)` → (status, json)."""
    parts = path.split("/")
    if len(parts) != 4 or parts[0] != "incidents" or parts[2] != "actions":
        raise ValueError(f"Documento inesperado: {path}")
    action = store.get(path)
    if not action:
        return {"skipped": "documento inexistente"}
    if action.get("type") not in BRIDGE_TYPES:
        store.mark(path, {"bridge_status": "rejected", "bridge_error": "type no soportado"})
        return {"skipped": "type"}
    uid = (action.get("actor") or {}).get("user_id")
    profile = store.get(f"users/{uid}") if uid else None
    try:
        body = build_bridge_event(parts[3], action, profile)
    except ValueError as exc:
        store.mark(path, {"bridge_status": "rejected", "bridge_error": str(exc)})
        return {"skipped": str(exc)}

    status, resp = post(bridge["url"], body, bridge["api_key"])
    if status >= 500:
        # Error transitorio: se relanza para que Eventarc reintente (idempotente por event_id en AWS)
        raise RuntimeError(f"/bridge/events respondió {status}")
    result = {"bridge_status": "processed" if status < 300 else "rejected", "bridge_http_status": status,
              "bridge_processed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if status >= 300:
        result["bridge_error"] = ((resp or {}).get("error") or {}).get("code", "ERROR")
    store.mark(path, result)
    return {"status": status, **result}


class FirestoreStore:  # pragma: no cover - requiere GCP
    def __init__(self, db):
        self.db = db

    def get(self, path):
        snap = self.db.document(path).get()
        return snap.to_dict() if snap.exists else None

    def mark(self, path, fields):
        self.db.document(path).update(fields)


def http_post(url, body, api_key):  # pragma: no cover - red
    import requests

    headers = {"x-api-key": api_key, "X-Correlation-Id": body.get("correlation_id", "")}
    r = requests.post(url, json=body, headers=headers,
                      timeout=10)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


def parse_bridge_secret(raw: str, url_env: str | None) -> dict:
    """Secreto = JSON `{api_key, url}` (copiado de AWS `arquifusion/<stage>/bridge-gcp`) o la API key en texto plano."""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {"api_key": data["api_key"], "url": url_env or data["url"]}
    except (ValueError, KeyError):
        pass
    if not url_env:
        raise ValueError("Falta BRIDGE_URL")
    return {"api_key": raw.strip(), "url": url_env}


# ======================================================================= entrypoints (Functions Framework)

_cache: dict = {}


def _db():  # pragma: no cover
    if "db" not in _cache:
        import firebase_admin
        from firebase_admin import firestore

        if not firebase_admin._apps:
            firebase_admin.initialize_app()
        _cache["db"] = firestore.client()
    return _cache["db"]


def _bridge_config():  # pragma: no cover
    if "bridge" not in _cache:
        from google.cloud import secretmanager

        name = os.environ["BRIDGE_SECRET"]  # projects/<p>/secrets/bridge-api-key/versions/latest
        raw = secretmanager.SecretManagerServiceClient().access_secret_version(name=name).payload.data.decode()
        _cache["bridge"] = parse_bridge_secret(raw, os.environ.get("BRIDGE_URL"))
    return _cache["bridge"]


def on_notification(cloud_event):  # pragma: no cover - entrypoint
    notification, attrs = decode_pubsub(cloud_event)
    _db()
    result = handle_notification(notification, FirestoreUsers(_db()), fcm_send)
    log.info(json.dumps({"msg": "push enviado", "correlation_id": attrs.get("correlation_id"), **result}))
    return result


def on_incident_action(cloud_event):  # pragma: no cover - entrypoint
    path = document_path(cloud_event)
    result = handle_action(path, FirestoreStore(_db()), http_post, _bridge_config())
    log.info(json.dumps({"msg": "acción reenviada", "document": path, **result}, default=str))
    return result


try:  # registra los entrypoints si está functions-framework (en GCP siempre)
    import functions_framework

    on_notification = functions_framework.cloud_event(on_notification)
    on_incident_action = functions_framework.cloud_event(on_incident_action)
except ImportError:  # pragma: no cover
    pass
