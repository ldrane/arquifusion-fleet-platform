import base64
import json
import shutil
import subprocess
from pathlib import Path

import gcp_auth
import gcp_rest
import pytest
import service

FIX = Path(__file__).parents[4] / "contracts" / "fixtures"
AUD = service.DEFAULT_AUDIENCE
EMAIL = "pubsub-push@p1.iam.gserviceaccount.com"
NOW = 1_700_000_000


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.fixture(scope="module")
def rsa_key(tmp_path_factory):
    if not shutil.which("openssl"):
        pytest.skip("openssl no disponible")
    key = tmp_path_factory.mktemp("k") / "k.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(key)],
        check=True,
        capture_output=True,
    )
    n, d = gcp_auth.parse_private_key(key.read_text())
    return n, d


def make_token(rsa_key, kid="k1", **overrides):
    n, d = rsa_key
    claims = {
        "iss": "https://accounts.google.com",
        "aud": AUD,
        "email": EMAIL,
        "email_verified": True,
        "iat": NOW,
        "exp": NOW + 3600,
        **overrides,
    }
    signing_input = f"{b64url(json.dumps({'alg': 'RS256', 'kid': kid}).encode())}.{b64url(json.dumps(claims).encode())}"
    return f"{signing_input}.{b64url(gcp_auth.sign_rs256(signing_input.encode(), n, d))}"


def verify(rsa_key, token, now=NOW):
    return service.verify_oidc(
        token, audience=AUD, email=EMAIL, keys={"k1": (rsa_key[0], 65537)}, verify_rs256=gcp_auth.verify_rs256, now=now
    )


# ---------------------------------------------------------------- OIDC


def test_oidc_valido(rsa_key):
    assert verify(rsa_key, make_token(rsa_key))["email"] == EMAIL


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "otra"},
        {"email": "intruso@x.iam.gserviceaccount.com"},
        {"email_verified": False},
        {"iss": "https://evil.example"},
        {"exp": NOW - 3600},
    ],
)
def test_oidc_rechaza_claims(rsa_key, overrides):
    with pytest.raises(service.Unauthorized):
        verify(rsa_key, make_token(rsa_key, **overrides))


def test_oidc_rechaza_firma_alterada_y_kid_desconocido(rsa_key):
    h, c, s = make_token(rsa_key).split(".")
    forged = b64url(
        json.dumps(
            {
                "iss": "https://accounts.google.com",
                "aud": AUD,
                "email": EMAIL,
                "email_verified": True,
                "exp": NOW + 9999,
            }
        ).encode()
    )
    with pytest.raises(service.Unauthorized):
        verify(rsa_key, f"{h}.{forged}.{s}")
    with pytest.raises(service.Unauthorized):
        verify(rsa_key, make_token(rsa_key, kid="otro"))
    with pytest.raises(service.Unauthorized):
        verify(rsa_key, "no-es-un-jwt")


def test_parse_jwks():
    jwks = {"keys": [{"kty": "RSA", "kid": "a", "n": b64url((12345).to_bytes(2, "big")), "e": "AQAB"}]}
    assert service.parse_jwks(jwks) == {"a": (12345, 65537)}


# ---------------------------------------------------------------- entrega


class FakeUsers:
    def __init__(self, docs):
        self.docs = docs
        self.removed = []

    def get(self, uid):
        return self.docs.get(uid)

    def by_role_zone(self, role, zones):
        return [(u, d) for u, d in self.docs.items() if d.get("role") == role and d.get("zone") in zones]

    def remove_tokens(self, uid, tokens):
        self.removed.append((uid, tokens))


def deps_for(users, sent, verify_fn=lambda token: {}):
    def send(tokens, title, body, data, link):
        sent.append((tokens, title, data, link))
        return [t for t in tokens if t.startswith("bad")]

    return {"verify": verify_fn, "users": lambda: users, "send": lambda: send}


def push_event(notification, token="tok", b64=False):
    envelope = {
        "message": {
            "data": base64.b64encode(json.dumps(notification).encode()).decode(),
            "attributes": {"correlation_id": notification["correlation_id"]},
            "messageId": "1",
        },
        "subscription": "projects/p1/subscriptions/notificaciones-push",
    }
    body = json.dumps(envelope)
    if b64:
        body = base64.b64encode(body.encode()).decode()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return {"httpMethod": "POST", "resource": "/bridge/push", "headers": headers, "body": body, "isBase64Encoded": b64}


def fixture_notification():
    return json.loads((FIX / "pubsub/notificacion.json").read_text(encoding="utf-8"))


def test_push_de_pubsub_envia_al_tecnico_y_limpia_tokens():
    users = FakeUsers({"u-tec-07": {"role": "tecnico", "zone": "norte", "fcm_tokens": ["ok1", "bad1"]}})
    sent = []
    resp = service.run(push_event(fixture_notification(), b64=True), deps_for(users, sent))
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {"sent": 1, "removed_tokens": 1}
    assert sent[0][0] == ["ok1", "bad1"] and sent[0][2]["incident_id"] == "INC-01JC8ZK"
    assert users.removed == [("u-tec-07", ["bad1"])]


def test_push_sin_token_o_con_token_invalido_da_401():
    sent = []
    resp = service.run(push_event(fixture_notification(), token=None), deps_for(FakeUsers({}), sent))
    assert resp["statusCode"] == 401

    def reject(token):
        raise service.Unauthorized("x")

    resp = service.run(push_event(fixture_notification()), deps_for(FakeUsers({}), sent, reject))
    assert resp["statusCode"] == 401 and sent == []


def test_falla_de_gcp_no_se_reintenta():
    class Broken(FakeUsers):
        def get(self, uid):
            raise RuntimeError("Firestore caído")

    resp = service.run(push_event(fixture_notification()), deps_for(Broken({}), []))
    assert resp["statusCode"] == 200 and json.loads(resp["body"])["error"] == "push_failed"


def test_invocacion_directa_por_rol_y_zona():
    users = FakeUsers(
        {
            "u-sup-01": {"role": "supervisor", "zone": "norte", "fcm_tokens": ["s1"]},
            "u-adm-01": {"role": "supervisor", "zone": "*", "fcm_tokens": ["a1"]},
            "u-sup-02": {"role": "supervisor", "zone": "sur", "fcm_tokens": ["x"]},
        }
    )
    notif = {**fixture_notification(), "target": {"role": "supervisor", "zone": "norte", "user_id": None}}
    sent = []
    result = service.run({"notification": notif, "attributes": {}}, deps_for(users, sent))
    assert result == {"sent": 2, "removed_tokens": 0}
    assert sorted(t for call in sent for t in call[0]) == ["a1", "s1"]


# ---------------------------------------------------------------- REST de Firestore y FCM


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url, body, headers))
        return self.responses.pop(0)


def test_firestore_rest_users():
    http = FakeHttp(
        [
            (404, {}),
            (
                200,
                {
                    "fields": {
                        "role": {"stringValue": "tecnico"},
                        "fcm_tokens": {"arrayValue": {"values": [{"stringValue": "t1"}]}},
                        "technician_id": {"nullValue": None},
                    }
                },
            ),
            (
                200,
                [
                    {"readTime": "x"},
                    {
                        "document": {
                            "name": "projects/p1/databases/(default)/documents/users/u-1",
                            "fields": {"zone": {"stringValue": "norte"}},
                        }
                    },
                ],
            ),
            (200, {}),
        ]
    )
    users = gcp_rest.FirestoreRestUsers("p1", lambda: "tok", request=http)
    assert users.get("nadie") is None
    assert users.get("u-tec-07") == {"role": "tecnico", "fcm_tokens": ["t1"], "technician_id": None}
    assert users.by_role_zone("supervisor", ["norte", "*"]) == [("u-1", {"zone": "norte"})]
    users.remove_tokens("u-1", ["t1"])

    _, url, query, headers = http.calls[2]
    assert url.endswith("/documents:runQuery") and headers["Authorization"] == "Bearer tok"
    filters = query["structuredQuery"]["where"]["compositeFilter"]["filters"]
    assert filters[1]["fieldFilter"]["op"] == "IN"
    write = http.calls[3][2]["writes"][0]["transform"]
    assert write["document"] == "projects/p1/databases/(default)/documents/users/u-1"
    assert write["fieldTransforms"][0]["removeAllFromArray"]["values"] == [{"stringValue": "t1"}]


def test_fcm_rest_detecta_tokens_invalidos_y_omite_link_relativo():
    unregistered = {"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}}
    http = FakeHttp([(200, {"name": "m1"}), (404, unregistered), (500, {"error": {"status": "INTERNAL"}})])
    send = gcp_rest.FcmRestSender("p1", lambda: "tok", request=http)
    assert send(["a", "b", "c"], "T", "B", {"k": "v"}, "/incidents/INC-1") == ["b"]
    msg = http.calls[0][2]["message"]
    assert http.calls[0][1] == "https://fcm.googleapis.com/v1/projects/p1/messages:send"
    assert msg["token"] == "a" and msg["data"] == {"k": "v"} and "webpush" not in msg

    http = FakeHttp([(200, {})])
    gcp_rest.FcmRestSender("p1", lambda: "tok", request=http)(["a"], "T", "B", {}, "https://app.example/x")
    assert http.calls[0][2]["message"]["webpush"] == {"fcm_options": {"link": "https://app.example/x"}}
