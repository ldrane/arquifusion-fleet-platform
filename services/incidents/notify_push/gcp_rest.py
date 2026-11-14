"""Firestore y FCM HTTP v1 por REST, sin SDK de Google (modo sin facturación de GCP).

Implementa las mismas interfaces que usa `notify_bridge` (gcp/functions/notify_bridge/main.py):
- `FirestoreRestUsers`: `get(uid)`, `by_role_zone(role, zones)`, `remove_tokens(uid, tokens)`.
- `FcmRestSender`: invocable `send(tokens, title, body, data, link)` → tokens inválidos.

Se autentica con la service account `aws-integration` (secreto `arquifusion/<stage>/gcp/service-account`):
`roles/datastore.user` + `roles/firebasecloudmessaging.admin` (infra/gcp/iam.tf, `gcp_billing = false`).
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger("notify_push")

SCOPES = "https://www.googleapis.com/auth/datastore https://www.googleapis.com/auth/firebase.messaging"
FIRESTORE = "https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents"
FCM_SEND = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"
# FCM marca así los tokens que ya no sirven (equivalen a UnregisteredError / SenderIdMismatchError del Admin SDK)
INVALID_TOKEN_CODES = {"UNREGISTERED", "SENDER_ID_MISMATCH"}


def http_request(method: str, url: str, body: dict | None, headers: dict, timeout: float = 8.0) -> tuple[int, object]:
    """Devuelve (status, json). No lanza por 4xx/5xx: el llamador decide."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - URLs fijas de Google
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw) if raw else {}
        except ValueError:
            return exc.code, {}


# ---------------------------------------------------------------- valores de Firestore (REST ⇄ Python)


def from_value(v: dict):
    if "stringValue" in v:
        return v["stringValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return float(v["doubleValue"])
    if "booleanValue" in v:
        return v["booleanValue"]
    if "timestampValue" in v:
        return v["timestampValue"]
    if "arrayValue" in v:
        return [from_value(x) for x in v["arrayValue"].get("values", [])]
    if "mapValue" in v:
        return from_fields(v["mapValue"].get("fields", {}))
    return None  # nullValue y tipos que no usamos (referenceValue, geoPointValue, bytesValue)


def from_fields(fields: dict) -> dict:
    return {k: from_value(v) for k, v in (fields or {}).items()}


def _str(s: str) -> dict:
    return {"stringValue": s}


# ---------------------------------------------------------------- Firestore users/{uid}


class FirestoreRestUsers:
    def __init__(self, project: str, token, request=http_request):
        self.base = FIRESTORE.format(project=project)
        self.token = token  # () -> access token
        self.request = request

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.token()}"}

    def get(self, uid: str) -> dict | None:
        status, doc = self.request("GET", f"{self.base}/users/{urllib.parse.quote(uid, safe='')}", None, self._h())
        if status == 404:
            return None
        if status >= 300:
            raise RuntimeError(f"Firestore GET users/{uid} respondió {status}")
        return from_fields(doc.get("fields", {}))

    def by_role_zone(self, role: str, zones: list[str]) -> list[tuple[str, dict]]:
        query = {
            "structuredQuery": {
                "from": [{"collectionId": "users"}],
                "where": {
                    "compositeFilter": {
                        "op": "AND",
                        "filters": [
                            {"fieldFilter": {"field": {"fieldPath": "role"}, "op": "EQUAL", "value": _str(role)}},
                            {
                                "fieldFilter": {
                                    "field": {"fieldPath": "zone"},
                                    "op": "IN",
                                    "value": {"arrayValue": {"values": [_str(z) for z in zones]}},
                                }
                            },
                        ],
                    }
                },
            }
        }
        status, rows = self.request("POST", f"{self.base}:runQuery", query, self._h())
        if status >= 300:
            raise RuntimeError(f"Firestore runQuery users respondió {status}")
        out = []
        for row in rows or []:
            doc = row.get("document") if isinstance(row, dict) else None
            if doc:  # las filas sin `document` solo traen readTime
                out.append((doc["name"].rsplit("/", 1)[-1], from_fields(doc.get("fields", {}))))
        return out

    def remove_tokens(self, uid: str, tokens: list[str]) -> None:
        name = f"{self.base}/users/{uid}".split("/v1/", 1)[1]  # projects/<p>/databases/(default)/documents/users/<uid>
        write = {
            "transform": {
                "document": name,
                "fieldTransforms": [
                    {"fieldPath": "fcm_tokens", "removeAllFromArray": {"values": [_str(t) for t in tokens]}}
                ],
            }
        }
        status, _ = self.request("POST", f"{self.base}:commit", {"writes": [write]}, self._h())
        if status >= 300:
            log.warning("No se pudieron quitar tokens de users/%s (HTTP %s)", uid, status)


# ---------------------------------------------------------------- FCM HTTP v1


def _fcm_error_code(resp) -> str:
    err = (resp or {}).get("error") or {}
    for d in err.get("details") or []:
        if d.get("errorCode"):
            return d["errorCode"]
    return err.get("status") or ""


class FcmRestSender:
    def __init__(self, project: str, token, request=http_request):
        self.url = FCM_SEND.format(project=project)
        self.token = token
        self.request = request

    def __call__(self, tokens, title, body, data, link) -> list[str]:
        """Un request por token (HTTP v1 no tiene multicast). Devuelve los tokens no registrados."""
        invalid = []
        for t in tokens:
            message = {"token": t, "notification": {"title": title, "body": body}, "data": data}
            if link.startswith("https://"):  # FCM exige URL absoluta HTTPS; el deep_link relativo viaja en `data`
                message["webpush"] = {"fcm_options": {"link": link}}
            status, resp = self.request(
                "POST", self.url, {"message": message}, {"Authorization": f"Bearer {self.token()}"}
            )
            if status < 300:
                continue
            code = _fcm_error_code(resp)
            if code in INVALID_TOKEN_CODES or status == 404:
                invalid.append(t)
            else:
                log.warning("FCM falló para un token: HTTP %s %s", status, code)
        return invalid
