"""Lectura del chat del incidente en Firestore por REST (RF-15, RF-16.8; contratos.md §5).

Alimenta la tarea `summarize_chat` de ia-gemini con SOLO la conversación (`incidents/{canal}/messages`):
las notas de resolución viajan aparte (`resolution_notes`) y el front las muestra en su propio bloque.

Sin SDK de Google: el access token sale de `gcp_auth.TokenSource` (JWT RS256 con la stdlib, mismo archivo que
usan notificar y notify_push; Terraform lo copia al zip). Service account del secreto
`arquifusion/<stage>/gcp/service-account` (`roles/datastore.user`).
"""
import json
import urllib.error
import urllib.parse
import urllib.request

DATASTORE_SCOPE = "https://www.googleapis.com/auth/datastore"
FIRESTORE = "https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents"
MAX_MESSAGES = 100  # los más recientes; acota el payload de la SFN (256 KB)
MAX_TEXT = 1000
SYSTEM_ROLES = {"sistema", "system"}


def http_request(method: str, url: str, body: dict | None, headers: dict, timeout: float = 8.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - URL fija de Google
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw) if raw else {}
        except ValueError:
            return exc.code, {}


def _value(v: dict):
    for k in ("stringValue", "timestampValue", "booleanValue"):
        if k in v:
            return v[k]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    return None


def to_message(fields: dict) -> dict | None:
    """Documento de Firestore → mensaje para summarize_chat. None si no es conversación (sistema o vacío)."""
    f = {k: _value(v) for k, v in (fields or {}).items()}
    text = str(f.get("text") or "").strip()
    if (str(f.get("role") or "").lower() in SYSTEM_ROLES) or not (text or f.get("quick_action")):
        return None
    return {
        "author_id": f.get("author_id"),
        "role": f.get("role"),
        "text": text[:MAX_TEXT],
        "quick_action": f.get("quick_action"),
        "created_at": f.get("created_at"),
    }


class FirestoreChat:
    """`messages(channel)` → mensajes del chat en orden cronológico (los MAX_MESSAGES más recientes)."""

    def __init__(self, project: str, token, request=http_request):
        self.base = FIRESTORE.format(project=project)
        self.token = token  # () -> access token
        self.request = request

    def messages(self, channel: str) -> list[dict]:
        parent = f"{self.base}/incidents/{urllib.parse.quote(channel, safe='')}"
        query = {
            "structuredQuery": {
                "from": [{"collectionId": "messages"}],
                "orderBy": [{"field": {"fieldPath": "created_at"}, "direction": "DESCENDING"}],
                "limit": MAX_MESSAGES,
            }
        }
        status, rows = self.request("POST", f"{parent}:runQuery", query, {"Authorization": f"Bearer {self.token()}"})
        if status >= 300:
            raise RuntimeError(f"Firestore runQuery incidents/{channel}/messages respondió {status}")
        out = []
        for row in rows or []:
            doc = row.get("document") if isinstance(row, dict) else None
            msg = to_message(doc.get("fields", {})) if doc else None
            if msg:
                out.append(msg)
        out.reverse()  # DESC → cronológico
        return out


def from_env(env) -> FirestoreChat:  # pragma: no cover - requiere Secrets Manager
    import boto3
    import gcp_auth

    secret = env.get("GCP_SA_SECRET_NAME") or f"arquifusion/{env.get('STAGE', 'dev')}/gcp/service-account"
    sa = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=secret)["SecretString"])
    tokens = gcp_auth.TokenSource(DATASTORE_SCOPE)
    return FirestoreChat(sa["project_id"], lambda: tokens.token(sa))
