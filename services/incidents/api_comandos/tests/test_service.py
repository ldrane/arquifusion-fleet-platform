import json
from pathlib import Path

import service

FIX = Path(__file__).parents[4] / "contracts" / "fixtures" / "api"


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeTable:
    def __init__(self, items=None, update_error=None):
        self.items = items or {}
        self.update_error = update_error
        self.updates = []
        self.deleted = []

    def get_item(self, Key):
        item = self.items.get((Key["pk"], Key.get("sk")))
        return {"Item": dict(item)} if item else {}

    def update_item(self, **kwargs):
        if self.update_error:
            raise FakeClientError(self.update_error)
        self.updates.append(kwargs)
        key = (kwargs["Key"]["pk"], kwargs["Key"]["sk"])
        item = dict(self.items.get(key, {}))
        for name, attr in kwargs.get("ExpressionAttributeNames", {}).items():
            item[attr] = kwargs["ExpressionAttributeValues"][":" + name[1:]]
        self.items[key] = item
        return {"Attributes": item}

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["pk"], Item.get("sk"))
        if key in self.items:
            raise FakeClientError("ConditionalCheckFailedException")
        self.items[key] = Item

    def delete_item(self, Key):
        self.deleted.append(Key)
        self.items.pop((Key["pk"], Key.get("sk")), None)


class FakeSfn:
    def __init__(self, error=None):
        self.error = error
        self.calls = []
        self.started = []

    def send_task_success(self, taskToken, output):
        if self.error:
            raise FakeClientError(self.error)
        self.calls.append((taskToken, json.loads(output)))

    def start_execution(self, stateMachineArn, input):
        self.started.append((stateMachineArn, json.loads(input)))
        return {"executionArn": "arn:exec:1"}


def incident(status="assigned", **extra):
    base = {
        "pk": "INC#INC-1",
        "sk": "META",
        "incident_id": "INC-1",
        "zone": "norte",
        "status": status,
        "ack_token": "TOKEN-ACK",
        "resolve_token": "TOKEN-RES",
        "execution_arn": "arn:exec",
        "assigned_technician_id": "TEC-07",
    }
    base.update(extra)
    return base


TECHS = {
    ("TECH#TEC-07", "META"): {
        "pk": "TECH#TEC-07",
        "sk": "META",
        "technician_id": "TEC-07",
        "user_id": "u-tec-07",
        "zone": "norte",
        "available": True,
        "location": {"lat": 1, "lon": 1, "zone": "norte"},
    },
    ("TECH#TEC-01", "META"): {
        "pk": "TECH#TEC-01",
        "sk": "META",
        "technician_id": "TEC-01",
        "user_id": "u-tec-01",
        "zone": "norte",
    },
}


def make_deps(inc=None, sfn=None, technicians=None):
    items = {("INC#INC-1", "META"): inc} if inc else {}
    return {
        "incidents": FakeTable(items),
        "technicians": technicians or FakeTable(dict(TECHS)),
        "idempotency": FakeTable(),
        "sfn": sfn or FakeSfn(),
        "retrain_arn": "arn:sfn:retrain",
    }


TEC07 = {"cognito:username": "u-tec-07", "custom:technician_id": "TEC-07", "custom:zone": "norte"}


def make_event(resource, method="POST", groups="tecnico", body=None, claims=None):
    if claims is None:
        claims = TEC07 if groups == "tecnico" else {"cognito:username": "u-sup", "custom:zone": "norte"}
    all_claims = {"cognito:groups": groups, **claims}
    return {
        "httpMethod": method,
        "resource": resource,
        "pathParameters": {"incident_id": "INC-1"},
        "headers": {"X-Correlation-Id": "cid-1"},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"claims": all_claims}},
    }


ACK = "/incidents/{incident_id}/ack"
ASSIGN = "/incidents/{incident_id}/assign"
RESOLVE = "/incidents/{incident_id}/resolve"
STATUS = "/technicians/me/status"


def body_of(resp):
    return json.loads(resp["body"])


def test_ack_accept_envia_token_y_actor_y_responde_incidente_completo():
    deps = make_deps(incident())
    resp = service.run(make_event(ACK, body={"decision": "accept"}), deps)
    assert resp["statusCode"] == 200
    body = body_of(resp)
    assert body["meta"] == {"pending_transition": "in_progress"}
    assert body["data"]["incident_id"] == "INC-1" and body["data"]["status"] == "assigned"
    for secret in ("ack_token", "resolve_token", "execution_arn", "pk", "sk"):
        assert secret not in body["data"]
    token, output = deps["sfn"].calls[0]
    assert token == "TOKEN-ACK"
    assert output["decision"] == "accept" and output["correlation_id"] == "cid-1"
    assert output["actor"] == {"type": "user", "user_id": "u-tec-07", "role": "tecnico", "technician_id": "TEC-07"}
    assert resp["headers"]["X-Correlation-Id"] == "cid-1"
    assert resp["headers"]["Access-Control-Allow-Origin"]


def test_ack_reject_pending_assigned():
    resp = service.run(make_event(ACK, body={"decision": "reject", "reason": "lejos"}), make_deps(incident()))
    assert body_of(resp)["meta"]["pending_transition"] == "assigned"


def test_ack_tecnico_no_asignado_403():
    claims = {"cognito:username": "u-tec-01", "custom:technician_id": "TEC-01", "custom:zone": "norte"}
    resp = service.run(make_event(ACK, body={"decision": "accept"}, claims=claims), make_deps(incident()))
    assert resp["statusCode"] == 403


def test_ack_mantenimiento_de_otra_zona_403():
    ev = make_event(
        ACK,
        groups="mantenimiento",
        body={"decision": "accept"},
        claims={"cognito:username": "u-m", "custom:zone": "sur"},
    )
    assert service.run(ev, make_deps(incident()))["statusCode"] == 403


def test_ack_rol_sin_permiso_403():
    resp = service.run(make_event(ACK, groups="operador", body={"decision": "accept"}), make_deps(incident()))
    assert resp["statusCode"] == 403
    assert body_of(resp)["error"]["code"] == "FORBIDDEN"


def test_sin_jwt_401():
    ev = make_event(ACK, body={"decision": "accept"})
    ev["requestContext"] = {}
    assert service.run(ev, make_deps(incident()))["statusCode"] == 401


def test_ack_decision_invalida_400():
    resp = service.run(make_event(ACK, body={"decision": "tal vez"}), make_deps(incident()))
    assert resp["statusCode"] == 400


def test_ack_incidente_inexistente_404():
    resp = service.run(make_event(ACK, body={"decision": "accept"}), make_deps(None))
    assert resp["statusCode"] == 404


def test_ack_estado_incorrecto_409():
    resp = service.run(make_event(ACK, body={"decision": "accept"}), make_deps(incident("in_progress")))
    assert resp["statusCode"] == 409
    assert body_of(resp)["error"]["code"] == "INCIDENT_STATE_INVALID"


def test_ack_token_ya_usado_409():
    deps = make_deps(incident(), sfn=FakeSfn(error="InvalidToken"))
    resp = service.run(make_event(ACK, body={"decision": "accept"}), deps)
    assert resp["statusCode"] == 409


def test_ack_step_functions_caido_503():
    deps = make_deps(incident(), sfn=FakeSfn(error="ServiceUnavailable"))
    resp = service.run(make_event(ACK, body={"decision": "accept"}), deps)
    assert resp["statusCode"] == 503


def test_assign_reasigna_y_avisa_al_workflow():
    deps = make_deps(incident())
    resp = service.run(make_event(ASSIGN, groups="supervisor", body={"technician_id": "TEC-01"}), deps)
    assert resp["statusCode"] == 200
    assert body_of(resp)["meta"] == {"pending_transition": "assigned"}
    token, output = deps["sfn"].calls[0]
    assert token == "TOKEN-ACK"
    assert output["decision"] == "reassign" and output["technician_id"] == "TEC-01"
    assert output["actor"]["role"] == "supervisor"


def test_assign_desde_detected_con_token_de_asignacion_manual_200():
    # #16: la SFN espera asignación manual (sin candidatos) con ack_token en estado detected
    deps = make_deps(incident("detected", assigned_technician_id=None))
    resp = service.run(make_event(ASSIGN, groups="mantenimiento", body={"technician_id": "TEC-07"}), deps)
    assert resp["statusCode"] == 200


def test_assign_tecnico_inexistente_404():
    resp = service.run(make_event(ASSIGN, groups="supervisor", body={"technician_id": "TEC-99"}), make_deps(incident()))
    assert resp["statusCode"] == 404


def test_assign_sin_token_todavia_409():
    inc = incident("detected")
    del inc["ack_token"]
    resp = service.run(make_event(ASSIGN, groups="supervisor", body={"technician_id": "TEC-07"}), make_deps(inc))
    assert resp["statusCode"] == 409


def test_resolve_usa_resolve_token():
    deps = make_deps(incident("in_progress"))
    body = {"resolution_notes": "Cambio de filtro", "components_replaced": ["CMP-014"], "cost_usd": 120.5}
    resp = service.run(make_event(RESOLVE, body=body), deps)
    assert resp["statusCode"] == 200
    assert body_of(resp)["meta"] == {"pending_transition": "resolved"}
    assert body_of(resp)["data"]["status"] == "in_progress"  # nunca un resolved que no esté en DynamoDB
    token, output = deps["sfn"].calls[0]
    assert token == "TOKEN-RES"
    assert output["components_replaced"] == ["CMP-014"] and output["actor"]["user_id"] == "u-tec-07"


def test_resolve_estado_incorrecto_409():
    resp = service.run(make_event(RESOLVE, body={"resolution_notes": "ok"}), make_deps(incident("assigned")))
    assert resp["statusCode"] == 409


def test_resolve_sin_notas_400():
    resp = service.run(make_event(RESOLVE, body={}), make_deps(incident("in_progress")))
    assert resp["statusCode"] == 400


def test_tecnico_status_fixture_conserva_zona_y_responde_technician():
    event = json.loads((FIX / "technician_status.event.json").read_text())
    # la fixture puede traer el resource con o sin /v1: ambas se aceptan
    deps = make_deps()
    resp = service.run(event, deps)
    assert resp["statusCode"] == 200
    data = body_of(resp)["data"]
    assert data["technician_id"] == "TEC-07" and data["available"] is True
    assert data["location"] == {"lat": -11.915, "lon": -76.3965, "zone": "norte"}
    assert "pk" not in data
    assert deps["technicians"].updates[0]["Key"] == {"pk": "TECH#TEC-07", "sk": "META"}


def test_tecnico_status_location_invalida_400():
    ev = make_event(STATUS, method="PUT", body={"location": {"lat": 200, "lon": 0}})
    assert service.run(ev, make_deps())["statusCode"] == 400


def test_tecnico_status_sin_technician_id_400():
    ev = make_event(STATUS, method="PUT", body={"available": True}, claims={"cognito:username": "u-x"})
    assert service.run(ev, make_deps())["statusCode"] == 400


def test_retrain_202():
    deps = make_deps()
    resp = service.run(make_event("/ml/retrain", groups="admin", claims={"cognito:username": "u-admin"}), deps)
    assert resp["statusCode"] == 202
    assert body_of(resp)["data"] == {"execution_arn": "arn:exec:1"}
    assert deps["sfn"].started[0][1]["requested_by"] == "u-admin"


def bridge(body):
    return {
        "httpMethod": "POST",
        "resource": "/bridge/events",
        "headers": {"x-api-key": "k"},
        "body": json.dumps(body),
        "requestContext": {},
    }


BRIDGE_ACK = {
    "event_id": "fs-9f3a1",
    "type": "incident.ack",
    "incident_id": "INC-1",
    "actor": {"user_id": "u-tec-07", "role": "tecnico"},
    "data": {"decision": "accept"},
    "occurred_at": "2026-11-13T15:06:10Z",
    "correlation_id": "cid-b",
}


def test_bridge_ack_valida_por_user_id_y_es_idempotente():
    deps = make_deps(incident())
    resp = service.run(bridge(BRIDGE_ACK), deps)
    assert resp["statusCode"] == 200
    assert body_of(resp)["data"] == {"processed": True, "duplicate": False}
    _, output = deps["sfn"].calls[0]
    assert output["actor"]["user_id"] == "u-tec-07" and output["correlation_id"] == "cid-b"
    again = service.run(bridge(BRIDGE_ACK), deps)
    assert body_of(again)["data"] == {"processed": True, "duplicate": True}
    assert len(deps["sfn"].calls) == 1


def test_bridge_ack_de_otro_tecnico_403():
    deps = make_deps(incident())
    body = {**BRIDGE_ACK, "event_id": "fs-2", "actor": {"user_id": "u-tec-01", "role": "tecnico"}}
    assert service.run(bridge(body), deps)["statusCode"] == 403


def test_bridge_invalido_400():
    assert service.run(bridge({"event_id": "x"}), make_deps())["statusCode"] == 400


def test_bridge_error_5xx_libera_idempotencia():
    deps = make_deps(incident(), sfn=FakeSfn(error="ServiceUnavailable"))
    assert service.run(bridge(BRIDGE_ACK), deps)["statusCode"] == 503
    assert deps["idempotency"].deleted == [{"pk": "BRG#fs-9f3a1"}]


def test_ruta_desconocida_404():
    resp = service.run(make_event("/otra", method="GET"), make_deps())
    assert resp["statusCode"] == 404
