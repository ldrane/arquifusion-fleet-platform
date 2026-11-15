import base64
import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from query_common import gcp, items  # noqa: E402

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
SA = {
    "client_email": "aws-integration@arquifusion-g27.iam.gserviceaccount.com",
    "private_key": KEY.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode(),
    "project_id": "arquifusion-g27",
}


class CryptoSigner:
    """Equivalente a google.auth.crypt.RSASigner para el test (RS256 = PKCS1v15 + SHA256)."""

    key_id = "kid-1"

    def sign(self, message: bytes) -> bytes:
        return KEY.sign(message, padding.PKCS1v15(), hashes.SHA256())


def _dec(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def test_custom_token_firmado_y_con_claims():
    tok = gcp.custom_token(
        SA,
        "u-tec-07",
        {"role": "tecnico", "zone": "norte", "technician_id": "TEC-07"},
        CryptoSigner(),
        now=1_700_000_000,
    )
    h, p, s = tok.split(".")
    header, payload = json.loads(_dec(h)), json.loads(_dec(p))
    assert header == {"alg": "RS256", "typ": "JWT", "kid": "kid-1"}
    assert payload["aud"] == gcp.FIREBASE_AUDIENCE and payload["iss"] == payload["sub"] == SA["client_email"]
    assert payload["exp"] - payload["iat"] == 3600 and payload["uid"] == "u-tec-07"
    assert payload["claims"]["technician_id"] == "TEC-07"
    KEY.public_key().verify(_dec(s), f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())


def test_custom_token_uid_invalido():
    with pytest.raises(ValueError):
        gcp.custom_token(SA, "", {}, CryptoSigner())


def test_load_service_account():
    class SM:
        def __init__(self, value):
            self.value = value

        def get_secret_value(self, SecretId):
            return {"SecretString": self.value}

    assert gcp.load_service_account("s", SM(json.dumps(SA)))["project_id"] == "arquifusion-g27"
    with pytest.raises(ValueError):
        gcp.load_service_account("s", SM("{}"))
    with pytest.raises(ValueError):
        gcp.load_service_account("s", SM("no-json"))


def test_valores_firestore_ida_y_vuelta():
    doc = {"a": None, "b": True, "c": 3, "d": 1.5, "e": "x", "f": {"g": [1, "h"]}}
    fields = gcp.to_fields(doc)
    assert fields["c"] == {"integerValue": "3"} and fields["b"] == {"booleanValue": True}
    assert {k: gcp.from_value(v) for k, v in fields.items()} == doc


def test_firestore_commit_en_lotes_y_array_union():
    calls = []

    def transport(method, url, body):
        calls.append((method, url, body))
        return 200, {"writeResults": []}

    fs = gcp.Firestore("p1", transport)
    w = fs.merge_array_union_write("users/u-tec-07", {"role": "tecnico", "zone": "norte"}, "fcm_tokens", ["t1"])
    assert w["update"]["name"] == "projects/p1/databases/(default)/documents/users/u-tec-07"
    assert w["updateMask"] == {"fieldPaths": ["role", "zone"]}
    assert w["updateTransforms"][0]["appendMissingElements"]["values"] == [{"stringValue": "t1"}]
    assert fs.commit([fs.delete_write(f"machines/M-{i}") for i in range(1201)]) == 1201
    assert len(calls) == 3 and calls[0][1].endswith("/documents:commit") and len(calls[0][2]["writes"]) == 500


def test_firestore_error():
    fs = gcp.Firestore("p1", lambda m, u, b: (403, {"error": {"status": "PERMISSION_DENIED"}}))
    with pytest.raises(gcp.FirestoreError):
        fs.commit([fs.delete_write("machines/X")])


def test_items_plain_y_proyecciones():
    assert items.plain({"a": Decimal("3"), "b": Decimal("1.5"), "c": [Decimal("2")]}) == {"a": 3, "b": 1.5, "c": [2]}
    t = items.technician(
        {
            "pk": "TECH#TEC-07",
            "technician_id": "TEC-07",
            "zone": "norte",
            "location": {"lat": Decimal("-11.9"), "lon": Decimal("-76.4")},
            "available": True,
        }
    )
    assert t["location"] == {"lat": -11.9, "lon": -76.4, "zone": "norte"}  # #11
    assert t["specialties"] == [] and t["current_load"] == 0 and "pk" not in t
    inc = items.incident({"incident_id": "I", "machine_id": "EX-023", "ack_token": "s", "status": "assigned"})
    assert inc["machine_ids"] == ["EX-023"] and "ack_token" not in inc and inc["escalated"] is False
    closed = items.incident(
        {
            "incident_id": "I",
            "machine_id": "EX-023",
            "status": "closed",
            "resolution_summary": "Resumen del chat",
            "resolution_notes": "Cambio de rodamientos",
            "resolved_by": {"user_id": "u-tec-07", "role": "tecnico"},
            "closed_at": "2026-11-14T10:00:00Z",
        }
    )
    # Resumen del chat y notas de resolución viajan por separado al front (RF-16.8)
    assert closed["resolution_summary"] == "Resumen del chat" and closed["resolution_notes"] == "Cambio de rodamientos"
    assert closed["resolved_by"] == {"user_id": "u-tec-07", "role": "tecnico"} and closed["closed_at"]
    assert items.inventory_alert({"stock": 1, "stock_min": 2, "stock_max": 5}) == "low_stock"
    assert items.inventory_alert({"stock": 6, "stock_min": 2, "stock_max": 5}) == "overstock"
    assert items.inventory_alert({"stock": 2, "stock_min": 2, "stock_max": 5}) == "none"
