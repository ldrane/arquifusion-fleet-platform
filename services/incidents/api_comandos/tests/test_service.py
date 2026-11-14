import json

import service


class FakeClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeTable:
    def __init__(self, items=None, update_error=None):
        self.items = items or {}
        self.update_error = update_error
        self.updates = []

    def get_item(self, Key):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}

    def update_item(self, **kwargs):
        if self.update_error:
            raise FakeClientError(self.update_error)
        self.updates.append(kwargs)


class FakeSfn:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def send_task_success(self, taskToken, output):
        if self.error:
            raise FakeClientError(self.error)
        self.calls.append((taskToken, json.loads(output)))


def incident(status="assigned", **extra):
    base = {
        "pk": "INC#INC-1",
        "sk": "META",
        "status": status,
        "ack_token": "TOKEN-ACK",
        "resolve_token": "TOKEN-RES",
        "assigned_technician_id": "TEC-07",
    }
    base.update(extra)
    return base


def make_deps(inc=None, sfn=None, technicians=None):
    items = {("INC#INC-1", "META"): inc} if inc else {}
    return {
        "incidents": FakeTable(items),
        "technicians": technicians or FakeTable({("TECH#TEC-07", "META"): {"pk": "TECH#TEC-07"}}),
        "sfn": sfn or FakeSfn(),
    }


def make_event(resource, method="POST", groups="tecnico", body=None, claims=None):
    all_claims = {"cognito:groups": groups, **(claims or {})}
    return {
        "httpMethod": method,
        "resource": resource,
        "pathParameters": {"incident_id": "INC-1"},
        "headers": {"X-Correlation-Id": "cid-1"},
        "body": json.dumps(body) if body is not None else None,
        "requestContext": {"authorizer": {"claims": all_claims}},
    }


ACK = "/v1/incidents/{incident_id}/ack"
ASSIGN = "/v1/incidents/{incident_id}/assign"
RESOLVE = "/v1/incidents/{incident_id}/resolve"
STATUS = "/v1/technicians/me/status"


def body_of(resp):
    return json.loads(resp["body"])


def test_ack_accept_envia_token_a_step_functions():
    deps = make_deps(incident())
    resp = service.run(make_event(ACK, body={"decision": "accept"}), deps)
    assert resp["statusCode"] == 200
    assert body_of(resp)["data"] == {"incident_id": "INC-1", "decision": "accept"}
    token, output = deps["sfn"].calls[0]
    assert token == "TOKEN-ACK"
    assert output["decision"] == "accept"
    assert output["correlation_id"] == "cid-1"
    assert resp["headers"]["X-Correlation-Id"] == "cid-1"


def test_ack_rol_sin_permiso_403():
    resp = service.run(make_event(ACK, groups="operador", body={"decision": "accept"}), make_deps(incident()))
    assert resp["statusCode"] == 403
    assert body_of(resp)["error"]["code"] == "FORBIDDEN"


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
    resp = service.run(make_event(ASSIGN, groups="supervisor", body={"technician_id": "TEC-07"}), deps)
    assert resp["statusCode"] == 200
    token, output = deps["sfn"].calls[0]
    assert token == "TOKEN-ACK"
    assert output["decision"] == "reassign"
    assert output["technician_id"] == "TEC-07"


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
    token, output = deps["sfn"].calls[0]
    assert token == "TOKEN-RES"
    assert output["components_replaced"] == ["CMP-014"]


def test_resolve_estado_incorrecto_409():
    resp = service.run(make_event(RESOLVE, body={"resolution_notes": "ok"}), make_deps(incident("assigned")))
    assert resp["statusCode"] == 409


def test_resolve_sin_notas_400():
    resp = service.run(make_event(RESOLVE, body={}), make_deps(incident("in_progress")))
    assert resp["statusCode"] == 400


def test_tecnico_status_actualiza_disponibilidad_y_ubicacion():
    deps = make_deps()
    event = make_event(
        STATUS,
        method="PUT",
        body={"available": False, "location": {"lat": -12.04, "lng": -77.03}},
        claims={"custom:technician_id": "TEC-07"},
    )
    resp = service.run(event, deps)
    assert resp["statusCode"] == 200
    assert deps["technicians"].updates[0]["Key"] == {"pk": "TECH#TEC-07", "sk": "META"}


def test_tecnico_status_sin_technician_id_400():
    resp = service.run(make_event(STATUS, method="PUT", body={"available": True}), make_deps())
    assert resp["statusCode"] == 400


def test_ruta_desconocida_404():
    resp = service.run(make_event("/v1/otra", method="GET"), make_deps())
    assert resp["statusCode"] == 404
