import json
from pathlib import Path

import service

FIX = Path(__file__).parents[4] / "contracts" / "fixtures" / "events"


class FakeClientError(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTable:
    def __init__(self):
        self.items = {}

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["pk"], Item.get("sk"))
        if key in self.items:
            raise FakeClientError()
        self.items[key] = Item


def eventbridge(name):
    entry = json.loads((FIX / name).read_text())[0]
    return {
        "id": "x",
        "source": entry["Source"],
        "detail-type": entry["DetailType"],
        "detail": json.loads(entry["Detail"]),
    }


def deps():
    return {"audit": FakeTable(), "incidents": FakeTable()}


def test_incident_state_changed_escribe_auditoria_e_historial():
    d = deps()
    out = service.run(eventbridge("incident_state_changed.json"), d)
    assert out == {"audit": True, "history": True}
    ((key, hist),) = d["incidents"].items.items()
    assert key == ("INC#INC-01JC8ZK", "EVT#2026-11-13T10:15:00Z#01JC8ZK5T7Y2N4Q8R3W6X9A1B2")
    assert hist["entity"] == "incident_event" and hist["event_type"] == "incident.assigned"
    assert hist["from"] == "detected" and hist["to"] == "assigned" and hist["technician_id"] == "TEC-07"
    for forbidden in ("incident_id", "status", "machine_id", "detected_at"):
        assert forbidden not in hist
    ((akey, audit),) = d["audit"].items.items()
    assert akey[0] == "incident#INC-01JC8ZK"
    assert audit["actor"] == {"type": "system", "user_id": None, "role": None}


def test_reintento_es_idempotente():
    d = deps()
    service.run(eventbridge("incident_state_changed.json"), d)
    assert service.run(eventbridge("incident_state_changed.json"), d) == {"audit": False, "history": False}


def test_anomalia_y_silencio_se_auditan_por_maquina():
    d = deps()
    service.run(eventbridge("anomaly_detected.json"), d)
    service.run(eventbridge("machine_silent.json"), d)
    pks = sorted(k[0] for k in d["audit"].items)
    assert pks == ["machine#CM-004", "machine#EX-023"]
    assert d["incidents"].items == {}


def test_f14_audit_data_descarta_tokens_recursivamente():
    ev = eventbridge("incident_state_changed.json")
    ev["detail"]["data"].update(
        {
            "ack_token": "SECRETO-1",
            "taskToken": "SECRETO-2",
            "nested": {"resolve_token": "SECRETO-3", "ok": 1, "items": [{"task_token": "SECRETO-4", "k": "v"}]},
            "execution_arn": "arn:exec",
        }
    )
    d = deps()
    service.run(ev, d)
    blob = json.dumps(list(d["audit"].items.values()) + list(d["incidents"].items.values()), default=str)
    for secret in ("SECRETO-1", "SECRETO-2", "SECRETO-3", "SECRETO-4", "arn:exec"):
        assert secret not in blob
    stored = next(iter(d["audit"].items.values()))["data"]
    assert stored["nested"]["ok"] == 1 and stored["nested"]["items"] == [{"k": "v"}]
