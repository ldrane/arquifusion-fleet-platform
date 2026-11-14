"""Integración AWS -> GCP de la Persona C (RF-05, RF-16, MH-MC-02, MH-SEC-07).

- La service account vive en Secrets Manager (`arquifusion/{stage}/gcp/service-account`, contratos.md §9).
- Custom token de Firebase: JWT RS256 firmado LOCALMENTE con la llave de la service account (no sale a Internet).
- Firestore: API REST `documents:commit` con un access token OAuth2 de la service account.

Por qué no `firebase-admin`: arrastra grpc + google-cloud-firestore (~60 MB descomprimido) y alarga el cold start.
Aquí solo hace falta `google-auth` (puro Python, ~1 MB con `rsa`/`pyasn1`), que llega por la layer de C
(`scripts/build_query_layer.sh`). Todo lo de red se inyecta para probar sin GCP.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any, Protocol

FIREBASE_AUDIENCE = "https://identitytoolkit.googleapis.com/google.identity.identitytoolkit.v1.IdentityToolkit"
FIRESTORE_SCOPE = "https://www.googleapis.com/auth/datastore"
FIRESTORE_API = "https://firestore.googleapis.com/v1"
MAX_WRITES_PER_COMMIT = 500  # límite de Firestore
CUSTOM_TOKEN_TTL_S = 3600  # máximo permitido por Firebase


class Signer(Protocol):
    key_id: str | None

    def sign(self, message: bytes) -> bytes: ...


# --------------------------------------------------------------------------- service account
def load_service_account(secret_name: str, secrets_client) -> dict:
    """Lee el JSON de la llave desde Secrets Manager.

    Falla con ValueError si el secreto está vacío o no es una llave.
    """
    raw = secrets_client.get_secret_value(SecretId=secret_name).get("SecretString") or ""
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"El secreto {secret_name} no es JSON") from exc
    for field in ("client_email", "private_key", "project_id"):
        if not info.get(field):
            raise ValueError(f"El secreto {secret_name} no tiene {field} (¿se cargó la llave? runbook H0 §6)")
    return info


def default_signer(sa_info: dict) -> Signer:
    from google.auth import crypt  # layer de C

    return crypt.RSASigner.from_service_account_info(sa_info)


# --------------------------------------------------------------------------- custom token
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def custom_token(sa_info: dict, uid: str, claims: dict, signer: Signer, now: int | None = None) -> str:
    """Custom token de Firebase.

    Formato de la doc de Firebase Auth "create custom tokens using a third-party JWT library".
    """
    if not uid or len(uid) > 128:
        raise ValueError("uid inválido para Firebase (1-128 caracteres)")
    iat = int(now if now is not None else time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    if getattr(signer, "key_id", None):
        header["kid"] = signer.key_id
    payload = {
        "iss": sa_info["client_email"],
        "sub": sa_info["client_email"],
        "aud": FIREBASE_AUDIENCE,
        "iat": iat,
        "exp": iat + CUSTOM_TOKEN_TTL_S,
        "uid": uid,
        "claims": claims,
    }
    compact = (",", ":")
    head_b64 = _b64(json.dumps(header, separators=compact).encode())
    body_b64 = _b64(json.dumps(payload, separators=compact).encode())
    signing_input = f"{head_b64}.{body_b64}"
    return f"{signing_input}.{_b64(signer.sign(signing_input.encode('ascii')))}"


# --------------------------------------------------------------------------- valores Firestore REST
def to_value(v: Any) -> dict:
    """Python plano -> `Value` de la API REST de Firestore."""
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, str):
        return {"stringValue": v}
    if isinstance(v, datetime):
        return {"timestampValue": v.strftime("%Y-%m-%dT%H:%M:%S.%fZ")}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {str(k): to_value(x) for k, x in v.items()}}}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [to_value(x) for x in v]}}
    raise TypeError(f"Tipo no soportado en Firestore: {type(v).__name__}")


def to_fields(doc: dict) -> dict:
    return {str(k): to_value(v) for k, v in doc.items()}


def from_value(v: dict) -> Any:
    """Inverso de `to_value` (lo usan los tests y la depuración)."""
    ((kind, x),) = v.items()
    if kind == "nullValue":
        return None
    if kind == "integerValue":
        return int(x)
    if kind == "mapValue":
        return {k: from_value(y) for k, y in (x.get("fields") or {}).items()}
    if kind == "arrayValue":
        return [from_value(y) for y in (x.get("values") or [])]
    return x


# --------------------------------------------------------------------------- Firestore REST
Transport = Callable[[str, str, dict], tuple[int, dict]]


class Firestore:
    """Cliente mínimo de Firestore (base `(default)`) sobre `documents:commit`.

    `transport(method, url, json_body) -> (status, json_response)` ya autenticado.
    """

    def __init__(self, project_id: str, transport: Transport, database: str = "(default)"):
        self.project_id = project_id
        self.root = f"projects/{project_id}/databases/{database}/documents"
        self._transport = transport

    def doc_name(self, path: str) -> str:
        return f"{self.root}/{path.strip('/')}"

    # ---- builders de writes
    def set_write(self, path: str, data: dict) -> dict:
        """Reemplaza el documento completo (crea si no existe)."""
        return {"update": {"name": self.doc_name(path), "fields": to_fields(data)}}

    def delete_write(self, path: str) -> dict:
        return {"delete": self.doc_name(path)}

    def merge_array_union_write(self, path: str, data: dict, array_field: str, values: Iterable[Any]) -> dict:
        """Actualiza solo los campos de `data` y agrega `values` al arreglo sin duplicar (arrayUnion)."""
        return {
            "update": {"name": self.doc_name(path), "fields": to_fields(data)},
            "updateMask": {"fieldPaths": sorted(data)},
            "updateTransforms": [
                {"fieldPath": array_field, "appendMissingElements": {"values": [to_value(v) for v in values]}}
            ],
        }

    # ---- envío
    def commit(self, writes: list[dict]) -> int:
        """Envía en lotes de 500 (cada lote es atómico). Devuelve cuántos writes se aplicaron."""
        done = 0
        for i in range(0, len(writes), MAX_WRITES_PER_COMMIT):
            chunk = writes[i : i + MAX_WRITES_PER_COMMIT]
            status, body = self._transport("POST", f"{FIRESTORE_API}/{self.root}:commit", {"writes": chunk})
            if status >= 300:
                raise FirestoreError(status, body)
            done += len(chunk)
        return done


class FirestoreError(RuntimeError):
    def __init__(self, status: int, body: dict):
        super().__init__(f"Firestore respondió {status}: {json.dumps(body)[:500]}")
        self.status = status


def authorized_transport(sa_info: dict) -> Transport:
    """Transport real: google-auth (credenciales con scope datastore) + urllib3 (ya viene en el runtime de Lambda)."""
    import urllib3
    from google.auth.transport.urllib3 import AuthorizedHttp
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_info(sa_info, scopes=[FIRESTORE_SCOPE])
    http = AuthorizedHttp(creds, http=urllib3.PoolManager(timeout=urllib3.Timeout(connect=3.0, read=8.0)))

    def transport(method: str, url: str, body: dict) -> tuple[int, dict]:
        resp = http.request(method, url, body=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            data = json.loads(resp.data or b"{}")
        except json.JSONDecodeError:
            data = {"raw": resp.data[:300].decode(errors="replace")}
        return resp.status, data

    return transport


def firestore_from_service_account(sa_info: dict, project_id: str | None = None) -> Firestore:
    return Firestore(project_id or sa_info["project_id"], authorized_transport(sa_info))
