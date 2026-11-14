import base64
import hashlib
import json
import subprocess
from pathlib import Path

import gcp_auth
import pytest
import service

FIX = Path(__file__).parents[4] / "contracts" / "fixtures"


def load(rel):
    return json.loads((FIX / rel).read_text())


RULES = load("seed/notification_rules.json")
TECHS = {t["technician_id"]: t for t in load("seed/technicians.json")}
INCIDENT = {
    "incident_id": "INC-01JC8ZK",
    "assigned_technician_id": "TEC-07",
    "ai_diagnosis": {
        "probable_cause": "desgaste de rodamiento",
        "suggested_action": "inspeccionar rodamientos",
        "top_factors": [{"variable": "vibration_mm_s", "z_score": 3.1, "direction": "high"}],
    },
}


def make_deps(throttle_ok=True):
    sent = {"pubsub": [], "sns": [], "throttle": []}

    def throttle(key, minutes):
        sent["throttle"].append((key, minutes))
        return throttle_ok

    deps = {
        "rules": lambda et: [r for r in RULES if r["event_type"] == et],
        "throttle": throttle,
        "incident": lambda iid: INCIDENT,
        "technician": lambda tid: TECHS.get(tid),
        "sns": lambda role, subject, body, attrs: sent["sns"].append((role, subject, body, attrs)),
        "pubsub": lambda payload, attrs: sent["pubsub"].append((payload, attrs)),
    }
    return deps, sent


def eventbridge(rel):
    entry = load(rel)[0]
    return {"source": entry["Source"], "detail-type": entry["DetailType"], "detail": json.loads(entry["Detail"])}


def test_incident_assigned_push_al_tecnico_con_shape_del_contrato():
    deps, sent = make_deps()
    out = service.run(eventbridge("events/incident_state_changed.json"), deps)
    payload, attrs = sent["pubsub"][0]
    expected = load("pubsub/notificacion.json")
    assert set(payload) == set(expected)
    assert payload["target"] == expected["target"] == {"role": "tecnico", "zone": "norte", "user_id": "u-tec-07"}
    assert payload["deep_link"] == expected["deep_link"]
    assert payload["event_type"] == "incident.assigned"
    assert "3.1σ" in payload["body"] and "rodamiento" in payload["body"]
    assert attrs == {
        "correlation_id": expected["correlation_id"],
        "incident_id": "INC-01JC8ZK",
        "event_type": "incident.assigned",
    }
    # tecnico: push + email; mantenimiento solo dashboard → nada
    assert {(s["role"], s["channel"]) for s in out["sent"]} == {("tecnico", "push"), ("tecnico", "email")}
    assert sent["sns"][0][0] == "tecnico"
    assert sent["throttle"] == []  # throttle_minutes = 0


def test_severidad_minima_filtra_reglas():
    deps, sent = make_deps()
    msg = {
        "event_type": "incident.detected",
        "incident_id": "INC-1",
        "machine_id": "EX-023",
        "zone": "norte",
        "severity": "medium",
        "correlation_id": "c",
    }
    out = service.run(msg, deps)
    assert {s["role"] for s in out["sent"]} == {"mantenimiento"}  # operador/supervisor exigen high
    assert sent["throttle"] == [("NTF#incident.detected#mantenimiento#INC-1", 15)]


def test_throttle_corta_el_envio():
    deps, sent = make_deps(throttle_ok=False)
    msg = {
        "event_type": "incident.detected",
        "incident_id": "INC-1",
        "machine_id": "EX-023",
        "zone": "norte",
        "severity": "critical",
        "correlation_id": "c",
    }
    out = service.run(msg, deps)
    assert out["sent"] == [] and set(out["throttled"]) == {"operador", "mantenimiento", "supervisor", "gerencia"}
    assert sent["pubsub"] == [] and sent["sns"] == []


def test_push_a_rol_sin_user_id():
    deps, sent = make_deps()
    msg = {
        "event_type": "incident.in_progress",
        "incident_id": "INC-1",
        "machine_id": "EX-023",
        "zone": "norte",
        "severity": "high",
        "correlation_id": "c",
    }
    service.run(msg, deps)
    assert sent["pubsub"][0][0]["target"] == {"role": "operador", "zone": "norte", "user_id": None}


def test_escalado_usa_tecnico_del_evento_y_su_throttle():
    deps, sent = make_deps()
    msg = {
        "event_type": "incident.escalated",
        "incident_id": "INC-1",
        "machine_id": "EX-023",
        "zone": "norte",
        "severity": "high",
        "technician_id": "TEC-01",
        "correlation_id": "c",
    }
    service.run(msg, deps)
    assert ("NTF#incident.escalated#tecnico#INC-1#TEC-01", 5) in sent["throttle"]
    assert sent["pubsub"][0][0]["target"]["user_id"] == "u-tec-01"


def test_canal_caido_no_tumba_los_demas():
    deps, sent = make_deps()

    def boom(*a):
        raise RuntimeError("pubsub caído")

    deps["pubsub"] = boom
    out = service.run(eventbridge("events/incident_state_changed.json"), deps)
    assert [s["channel"] for s in out["sent"]] == ["email"]


@pytest.mark.skipif(subprocess.run(["which", "openssl"], capture_output=True).returncode != 0, reason="sin openssl")
def test_firma_rs256_verificable(tmp_path):
    key = tmp_path / "k.pem"
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(key)],
        check=True,
        capture_output=True,
    )
    pub = tmp_path / "p.pem"
    subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout", "-out", str(pub)], check=True, capture_output=True)
    sa = {"client_email": "aws@x.iam.gserviceaccount.com", "private_key": key.read_text(), "private_key_id": "k1"}
    jwt = gcp_auth.make_jwt(sa, gcp_auth.PUBSUB_SCOPE, now=1_700_000_000)
    signing_input, sig = jwt.rsplit(".", 1)
    (tmp_path / "msg").write_bytes(signing_input.encode())
    (tmp_path / "sig").write_bytes(base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)))
    res = subprocess.run(
        ["openssl", "dgst", "-sha256", "-verify", str(pub), "-signature", str(tmp_path / "sig"), str(tmp_path / "msg")],
        capture_output=True,
        text=True,
    )
    assert "Verified OK" in res.stdout
    claims = json.loads(base64.urlsafe_b64decode(signing_input.split(".")[1] + "=="))
    assert claims["scope"] == gcp_auth.PUBSUB_SCOPE and claims["exp"] - claims["iat"] == 3600
    assert hashlib.sha256(b"x").digest()  # sanity


def test_publisher_pide_token_y_publica():
    calls = []

    def fake_post(url, body, headers, timeout=5.0):
        calls.append((url, body, headers))
        if url == gcp_auth.TOKEN_URL:
            return {"access_token": "tok", "expires_in": 3600}
        return {"messageIds": ["42"]}

    pub = gcp_auth.PubSubPublisher(lambda: {"project_id": "p1"}, "notificaciones", http_post=fake_post)
    pub._access_token = lambda sa: "tok"  # sin llave real en este test
    assert pub.publish({"a": 1}, {"incident_id": "INC-1", "x": None}) == "42"
    url, body, headers = calls[-1]
    assert url == "https://pubsub.googleapis.com/v1/projects/p1/topics/notificaciones:publish"
    msg = json.loads(body)["messages"][0]
    assert json.loads(base64.b64decode(msg["data"])) == {"a": 1}
    assert msg["attributes"] == {"incident_id": "INC-1"}
    assert headers["Authorization"] == "Bearer tok"


def test_escalado_sin_candidatos_no_notifica_al_tecnico():
    """technician_id explícitamente null (EmitirSinCandidatos): se salta la regla `tecnico`."""
    deps, sent = make_deps()
    msg = {
        "event_type": "incident.escalated",
        "incident_id": "INC-1",
        "machine_id": "EX-023",
        "zone": "norte",
        "severity": "high",
        "technician_id": None,
        "correlation_id": "c",
    }
    out = service.run(msg, deps)
    assert all(s["role"] != "tecnico" for s in out["sent"])
    assert not any("#tecnico#" in k for k, _ in sent["throttle"])
