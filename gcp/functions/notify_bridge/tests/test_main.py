import base64
import json
from datetime import UTC, datetime
from pathlib import Path

import main
import pytest

FIX = Path(__file__).parents[4] / "contracts" / "fixtures"


class FakeEvent(dict):
    def __init__(self, data=None, **attrs):
        super().__init__(attrs)
        self.data = data


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


def pubsub_event(payload):
    data = base64.b64encode(json.dumps(payload).encode()).decode()
    return FakeEvent({"message": {"data": data, "attributes": {"correlation_id": payload["correlation_id"]}}})


def test_fixture_push_al_tecnico_y_limpia_tokens_invalidos():
    notif = json.loads((FIX / "pubsub/notificacion.json").read_text())
    decoded, attrs = main.decode_pubsub(pubsub_event(notif))
    assert decoded == notif and attrs["correlation_id"] == notif["correlation_id"]
    users = FakeUsers(
        {
            "u-tec-07": {"role": "tecnico", "zone": "norte", "fcm_tokens": ["ok", "muerto"]},
            "u-tec-01": {"role": "tecnico", "zone": "norte", "fcm_tokens": ["otro"]},
        }
    )
    calls = []

    def send(tokens, title, body, data, link):
        calls.append((tokens, title, body, data, link))
        return ["muerto"]

    out = main.handle_notification(decoded, users, send)
    assert out == {"sent": 1, "removed_tokens": 1}
    tokens, title, body, data, link = calls[0]
    assert tokens == ["ok", "muerto"] and title == notif["title"] and link == "/incidents/INC-01JC8ZK"
    assert data["incident_id"] == "INC-01JC8ZK" and all(isinstance(v, str) for v in data.values())
    assert users.removed == [("u-tec-07", ["muerto"])]


def test_push_por_rol_y_zona_incluye_globales():
    users = FakeUsers(
        {
            "u-op-01": {"role": "operador", "zone": "norte", "fcm_tokens": ["a"]},
            "u-op-02": {"role": "operador", "zone": "sur", "fcm_tokens": ["b"]},
            "u-op-03": {"role": "operador", "zone": "*", "fcm_tokens": ["c"]},
            "u-sin": {"role": "operador", "zone": "norte", "fcm_tokens": []},
        }
    )
    sent = []
    notif = {"target": {"role": "operador", "zone": "norte", "user_id": None}, "title": "t", "body": "b"}
    main.handle_notification(notif, users, lambda t, *a: sent.extend(t) or [])
    assert sorted(sent) == ["a", "c"]


class FakeStore:
    def __init__(self, docs):
        self.docs = docs
        self.marks = []

    def get(self, path):
        return self.docs.get(path)

    def mark(self, path, fields):
        self.marks.append((path, fields))


ACTION_PATH = "incidents/INC-01JC8ZK/actions/fs-9f3a1"
ACTION = {
    "type": "incident.ack",
    "incident_id": "INC-01JC8ZK",
    "actor": {"user_id": "u-tec-07", "role": "tecnico"},
    "data": {"decision": "accept"},
    "occurred_at": datetime(2026, 11, 13, 15, 6, 10, tzinfo=UTC),
    "correlation_id": "7c1e4b1a-0d2f-4a55-9c50-3b3f0a6f1e11",
}
BRIDGE = {"url": "https://x/v1/bridge/events", "api_key": "k"}


def test_accion_se_reenvia_como_bridge_event():
    store = FakeStore(
        {ACTION_PATH: ACTION, "users/u-tec-07": {"role": "tecnico", "zone": "norte", "technician_id": "TEC-07"}}
    )
    posted = []

    def post(url, body, key):
        posted.append((url, body, key))
        return 200, {"data": {"processed": True, "duplicate": False}}

    ev = FakeEvent(document="documents/" + ACTION_PATH)
    out = main.handle_action(main.document_path(ev), store, post, BRIDGE)
    url, body, key = posted[0]
    assert url == BRIDGE["url"] and key == "k"
    assert body == {
        "event_id": "fs-9f3a1",
        "type": "incident.ack",
        "incident_id": "INC-01JC8ZK",
        "actor": {"user_id": "u-tec-07", "role": "tecnico", "technician_id": "TEC-07", "zone": "norte"},
        "data": {"decision": "accept"},
        "occurred_at": "2026-11-13T15:06:10Z",
        "correlation_id": "7c1e4b1a-0d2f-4a55-9c50-3b3f0a6f1e11",
    }
    assert out["bridge_status"] == "processed" and store.marks[0][1]["bridge_status"] == "processed"


def test_rol_falsificado_se_rechaza_sin_llamar_a_aws():
    store = FakeStore(
        {
            ACTION_PATH: {**ACTION, "actor": {"user_id": "u-tec-07", "role": "admin"}},
            "users/u-tec-07": {"role": "tecnico", "zone": "norte"},
        }
    )
    out = main.handle_action(ACTION_PATH, store, lambda *a: pytest.fail("no debe llamar"), BRIDGE)
    assert "skipped" in out and store.marks[0][1]["bridge_status"] == "rejected"


def test_5xx_relanza_para_reintento_y_4xx_marca_rechazo():
    store = FakeStore({ACTION_PATH: ACTION, "users/u-tec-07": {"role": "tecnico", "zone": "*"}})
    with pytest.raises(RuntimeError):
        main.handle_action(ACTION_PATH, store, lambda *a: (503, {}), BRIDGE)
    out = main.handle_action(
        ACTION_PATH, store, lambda *a: (409, {"error": {"code": "INCIDENT_STATE_INVALID"}}), BRIDGE
    )
    assert out["bridge_status"] == "rejected" and out["bridge_error"] == "INCIDENT_STATE_INVALID"


def test_secreto_json_o_texto():
    assert main.parse_bridge_secret('{"api_key": "k", "url": "u"}', None) == {"api_key": "k", "url": "u"}
    assert main.parse_bridge_secret("k2\n", "https://x") == {"api_key": "k2", "url": "https://x"}
    with pytest.raises(ValueError):
        main.parse_bridge_secret("k2", None)
