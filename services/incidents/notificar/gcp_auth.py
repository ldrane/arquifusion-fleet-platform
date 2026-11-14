"""Autenticación con GCP y publicación REST en Pub/Sub sin dependencias externas (RF-10.2, MH-MC-02, contratos.md §4).

La Lambda no trae `google-auth` ni `cryptography`: firmamos el JWT RS256 de la service account con
aritmética de enteros de Python (PKCS#1 v1.5 + SHA-256) y lo cambiamos por un access token OAuth2
(grant `jwt-bearer`). El token se cachea por contenedor (~55 min).

También lo usa `notify_push` (se copia en su zip): `TokenSource` para Firestore/FCM y `verify_rs256` para
validar el token OIDC con el que Pub/Sub firma las entregas push.
"""
import base64
import hashlib
import json
import time
import urllib.request

TOKEN_URL = "https://oauth2.googleapis.com/token"
PUBSUB_SCOPE = "https://www.googleapis.com/auth/pubsub"
PUBSUB_URL = "https://pubsub.googleapis.com/v1/projects/{project}/topics/{topic}:publish"
# DigestInfo DER de SHA-256 (RFC 8017 §9.2)
_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


# ---------- DER mínimo para leer la llave PKCS#8 / PKCS#1 ----------

def _read_tlv(data: bytes, pos: int) -> tuple[int, bytes, int]:
    tag = data[pos]
    length = data[pos + 1]
    pos += 2
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(data[pos : pos + n], "big")
        pos += n
    return tag, data[pos : pos + length], pos + length


def _sequence(data: bytes) -> list[tuple[int, bytes]]:
    out, pos = [], 0
    while pos < len(data):
        tag, value, pos = _read_tlv(data, pos)
        out.append((tag, value))
    return out


def parse_private_key(pem: str) -> tuple[int, int]:
    """Devuelve (n, d) de una llave RSA en PEM PKCS#8 (`BEGIN PRIVATE KEY`) o PKCS#1."""
    body = "".join(line for line in pem.strip().splitlines() if not line.startswith("-----"))
    der = base64.b64decode(body)
    _, outer, _ = _read_tlv(der, 0)
    items = _sequence(outer)
    if len(items) >= 3 and items[1][0] == 0x30 and items[2][0] == 0x04:  # PKCS#8: envuelve la RSAPrivateKey
        _, rsa_seq, _ = _read_tlv(items[2][1], 0)
        items = _sequence(rsa_seq)
    ints = [int.from_bytes(v, "big") for tag, v in items if tag == 0x02]
    # RSAPrivateKey: version, n, e, d, p, q, dp, dq, qinv
    return ints[1], ints[3]


def _emsa_pkcs1(message: bytes, k: int) -> bytes:
    """EMSA-PKCS1-v1_5 con SHA-256 (RFC 8017 §9.2)."""
    t = _SHA256_PREFIX + hashlib.sha256(message).digest()
    return b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t


def sign_rs256(message: bytes, n: int, d: int) -> bytes:
    k = (n.bit_length() + 7) // 8
    return pow(int.from_bytes(_emsa_pkcs1(message, k), "big"), d, n).to_bytes(k, "big")


def verify_rs256(message: bytes, signature: bytes, n: int, e: int) -> bool:
    """Verifica una firma RS256 con la llave pública (n, e)."""
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    return pow(s, e, n).to_bytes(k, "big") == _emsa_pkcs1(message, k)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make_jwt(sa: dict, scope: str, now: int | None = None) -> str:
    now = int(now or time.time())
    header = {"alg": "RS256", "typ": "JWT", "kid": sa.get("private_key_id")}
    claims = {"iss": sa["client_email"], "scope": scope, "aud": TOKEN_URL, "iat": now, "exp": now + 3600}
    signing_input = f"{_b64url(json.dumps(header).encode())}.{_b64url(json.dumps(claims).encode())}"
    n, d = parse_private_key(sa["private_key"])
    return f"{signing_input}.{_b64url(sign_rs256(signing_input.encode(), n, d))}"


def _post(url: str, body: bytes, headers: dict, timeout: float = 5.0) -> dict:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - URL fija de Google
        return json.loads(resp.read() or b"{}")


class TokenSource:
    """Access token OAuth2 de la service account para `scope`, cacheado hasta 5 min antes de vencer."""

    def __init__(self, scope: str, http_post=_post):
        self._scope = scope
        self._post = http_post
        self._token: str | None = None
        self._token_exp = 0.0

    def token(self, sa: dict) -> str:
        if self._token and time.time() < self._token_exp:
            return self._token
        assertion = make_jwt(sa, self._scope)
        body = f"grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer&assertion={assertion}".encode()
        resp = self._post(TOKEN_URL, body, {"Content-Type": "application/x-www-form-urlencoded"})
        self._token = resp["access_token"]
        self._token_exp = time.time() + int(resp.get("expires_in", 3600)) - 300
        return self._token


class PubSubPublisher:
    """Publica en el topic `notificaciones` con la service account de Secrets Manager."""

    def __init__(self, sa_provider, topic: str, http_post=_post):
        self._sa_provider = sa_provider
        self._topic = topic
        self._post = http_post
        self._tokens = TokenSource(PUBSUB_SCOPE, http_post)

    def _access_token(self, sa: dict) -> str:
        return self._tokens.token(sa)

    def publish(self, message: dict, attributes: dict) -> str:
        sa = self._sa_provider()
        url = PUBSUB_URL.format(project=sa["project_id"], topic=self._topic)
        data = base64.b64encode(json.dumps(message, ensure_ascii=False).encode()).decode()
        payload = {"messages": [{"data": data, "attributes": {k: str(v) for k, v in attributes.items() if v}}]}
        headers = {"Authorization": f"Bearer {self._access_token(sa)}", "Content-Type": "application/json"}
        resp = self._post(url, json.dumps(payload).encode(), headers)
        return (resp.get("messageIds") or [""])[0]
