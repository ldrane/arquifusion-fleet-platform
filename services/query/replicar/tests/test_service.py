"""replicar: Streams (formato real de DynamoDB) -> writes de Firestore REST."""

import json
import sys
from pathlib import Path

from boto3.dynamodb.types import TypeSerializer

HERE = Path(__file__).resolve()
REPO = HERE.parents[4]
sys.path[:0] = [str(HERE.parents[1]), str(HERE.parents[2] / "common"), str(REPO / "services" / "shared")]

import service  # noqa: E402
from query_common import gcp  # noqa: E402

SEED = REPO / "contracts" / "fixtures" / "seed"
ENV = {"TABLE_MACHINES": "arquifusion-dev-machines", "REPLICA_HEARTBEAT_S": "300"}
_ser = TypeSerializer()


def _img(d):
    return {
        k: _ser.serialize(json.loads(json.dumps(v), parse_float=__import__("decimal").Decimal)) for k, v in d.items()
    }


def rec(table, name, new=None, old=None, keys=None):
    r = {
        "eventName": name,
        "eventSourceARN": f"arn:aws:dynamodb:us-east-1:1:table/arquifusion-dev-{table}/stream/2026",
        "dynamodb": {"Keys": _img(keys or {"pk": (new or old)["pk"], "sk": (new or old)["sk"]})},
    }
    if new:
        r["dynamodb"]["NewImage"] = _img(new)
    if old:
        r["dynamodb"]["OldImage"] = _img(old)
    return r


class FakeFS(gcp.Firestore):
    def __init__(self):
        self.sent = []
        super().__init__("p1", lambda m, u, b: (self.sent.append(b) or 200, {}))

    def docs(self):
        out = {}
        for body in self.sent:
            for w in body["writes"]:
                if "delete" in w:
                    out[w["delete"].split("/documents/")[1]] = None
                else:
                    name = w["update"]["name"].split("/documents/")[1]
                    out[name] = {k: gcp.from_value(v) for k, v in w["update"]["fields"].items()}
        return out


SEED_EX023 = next(m for m in json.loads((SEED / "machines.json").read_text()) if m["machine_id"] == "EX-023")
MACHINE = {
    "pk": "OP-01#EX-023",
    "sk": "META",
    "entity": "machines",
    **{k: v for k, v in SEED_EX023.items() if v is not None},
    "last_seen_at": "2026-11-14T10:00:10Z",
}
TECH = {
    "pk": "TECH#TEC-07",
    "sk": "META",
    "technician_id": "TEC-07",
    "name": "Pedro Rojas",
    "zone": "norte",
    "specialties": ["motor"],
    "location": {"lat": -11.915, "lon": -76.3965},
    "available": True,
    "shift": "day",
    "current_load": 1,
    "user_id": "u-tec-07",
}
INC = {
    "pk": "INC#INC-01",
    "sk": "META",
    "incident_id": "INC-01",
    "machine_id": "EX-023",
    "zone": "norte",
    "severity": "high",
    "status": "assigned",
    "assigned_technician_id": "TEC-07",
    "detected_at": "2026-11-14T10:00:00Z",
    "ack_token": "SECRETO",
    "resolve_token": "SECRETO2",
    "execution_arn": "arn:x",
    "correlation_id": "cid-1",
}


def test_replica_maquina_tecnico_incidente_y_secretos():
    fs = FakeFS()
    stats = service.run(
        {
            "Records": [
                rec("machines", "INSERT", MACHINE),
                rec("technicians", "MODIFY", TECH, TECH | {"available": False}),
                rec("incidents", "INSERT", INC),
            ]
        },
        fs,
        ENV,
    )
    docs = fs.docs()
    assert stats["written"] == 3
    m = docs["machines/EX-023"]
    assert m["location"]["zone"] == "norte" and m["model"] == "CAT-336" and "pk" not in m and "latest_reading" not in m
    assert m["open_incident_id"] is None and m["health_score"] == 85
    t = docs["technicians/TEC-07"]
    assert t["location"] == {"lat": -11.915, "lon": -76.3965, "zone": "norte"} and t["zone"] == "norte"  # #11
    i = docs["incidents/INC-01"]
    assert i["machine_ids"] == ["EX-023"] and i["correlation_id"] == "cid-1"
    assert not {"ack_token", "resolve_token", "execution_arn", "pk", "sk"} & set(i)


def test_ignora_evt_y_borra_en_remove():
    fs = FakeFS()
    evt = {"pk": "INC#INC-01", "sk": "EVT#2026-11-14T10:00:01Z#e1", "entity": "incident_event", "event_type": "x"}
    stats = service.run({"Records": [rec("incidents", "INSERT", evt), rec("technicians", "REMOVE", old=TECH)]}, fs, ENV)
    assert stats["ignored"] == 1 and fs.docs() == {"technicians/TEC-07": None}


def test_throttle_de_maquinas():
    later = MACHINE | {"last_seen_at": "2026-11-14T10:01:10Z", "operating_hours": 3582.2, "health_score": 83}
    assert not service.machine_needs_write(later, MACHINE, 300)  # solo ruido, mismo bucket de 5 min
    assert service.machine_needs_write(later | {"severity": "high"}, MACHINE, 300)  # cambio visible
    assert service.machine_needs_write(later | {"health_score": 70}, MACHINE, 300)  # salud cae >= 5
    assert service.machine_needs_write(later | {"open_incident_id": "INC-9"}, MACHINE, 300)
    assert service.machine_needs_write(
        later | {"last_seen_at": "2026-11-14T10:05:00Z"}, MACHINE, 300
    )  # cruza el bucket
    assert service.machine_needs_write(later, MACHINE, 0)
    fs = FakeFS()
    stats = service.run({"Records": [rec("machines", "MODIFY", later, MACHINE)]}, fs, ENV)
    assert stats["throttled"] == 1 and stats["written"] == 0 and fs.sent == []


def test_el_ultimo_cambio_del_lote_gana():
    fs = FakeFS()
    a = INC | {"status": "assigned"}
    b = INC | {"status": "in_progress"}
    service.run({"Records": [rec("incidents", "MODIFY", a, INC), rec("incidents", "MODIFY", b, a)]}, fs, ENV)
    assert fs.docs()["incidents/INC-01"]["status"] == "in_progress" and len(fs.sent[0]["writes"]) == 1


def test_table_of():
    assert (
        service.table_of({"eventSourceARN": "arn:aws:dynamodb:r:1:table/arquifusion-c-incidents/stream/x"})
        == "incidents"
    )
    assert service.table_of({"eventSourceARN": "arn:aws:dynamodb:r:1:table/arquifusion-c-anomalies/stream/x"}) is None


def test_f36_handler_fija_correlation_id(monkeypatch):
    import handler as replicar_handler

    seen = []
    monkeypatch.setattr(replicar_handler.logger, "set_correlation_id", seen.append)
    monkeypatch.setattr(replicar_handler.service, "run", lambda event: {"ok": 1})
    from types import SimpleNamespace

    ctx = SimpleNamespace(
        function_name="replicar", memory_limit_in_mb=128, invoked_function_arn="arn:x", aws_request_id="r-1"
    )
    out = replicar_handler.handler({"Records": []}, ctx)
    assert out == {"ok": 1} and len(seen) == 1 and len(seen[0]) == 36
