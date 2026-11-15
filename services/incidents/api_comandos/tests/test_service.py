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


class FakeSsm:
    def __init__(self, value='{"enabled": false}'):
        self.value = value
        self.puts = []

    def get_parameter(self, Name):
        return {"Parameter": {"Name": Name, "Value": self.value}}

    def put_parameter(self, Name, Value, Type, Overwrite):
        self.puts.append({"Name": Name, "Value": Value, "Type": Type, "Overwrite": Overwrite})
        self.value = Value


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

MACHINES = {
    ("OP-01#EX-023", "META"): {
        "pk": "OP-01#EX-023",
        "sk": "META",
        "machine_id": "EX-023",
        "model": "CAT-336",
        "zone": "norte",
        "status": "operational",
        "health_score": 91,
        "severity": "info",
        "open_incident_id": None,
    },
}

TG_CFG = {
    "bot_token": "123:abc",
    "chat_ids": ["-100"],
    "webhook_secret": "s3cret",
    "links": {"-100": {"user_id": "u-tec-07", "role": "tecnico", "technician_id": "TEC-07", "zone": "norte"}},
}


def make_deps(inc=None, sfn=None, technicians=None, telegram=None):
    items = {("INC#INC-1", "META"): inc} if inc else {}
    deps = {
        "incidents": FakeTable(items),
        "machines": FakeTable(dict(MACHINES)),
        "technicians": technicians or FakeTable(dict(TECHS)),
        "idempotency": FakeTable(),
        "sfn": sfn or FakeSfn(),
        "ssm": FakeSsm(),
        "retrain_arn": "arn:sfn:retrain",
        "sim_state_param": "/arquifusion/dev/sim/state",
        "telegram_config": lambda: telegram if telegram is not None else TG_CFG,
        "tg_send": lambda method, payload: deps.setdefault("telegram_sent", []).append((method, payload)),
        "operation_id": "OP-01",
    }
    return deps


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


# --------------------------------------------------------------------------- auditoría: F-11, F-20, F-21, F-22, F-37
def test_f11_supervisor_sin_zona_403_y_con_asterisco_ok():
    body = {"technician_id": "TEC-01"}
    sin_zona = make_event(ASSIGN, groups="supervisor", body=body, claims={"cognito:username": "u-sup"})
    assert service.run(sin_zona, make_deps(incident()))["statusCode"] == 403
    vacia = make_event(ASSIGN, groups="supervisor", body=body, claims={"cognito:username": "u", "custom:zone": ""})
    assert service.run(vacia, make_deps(incident()))["statusCode"] == 403
    global_ = make_event(ASSIGN, groups="supervisor", body=body, claims={"cognito:username": "u", "custom:zone": "*"})
    assert service.run(global_, make_deps(incident()))["statusCode"] == 200


def test_f11_admin_sin_zona_sigue_siendo_global():
    ev = make_event(ASSIGN, groups="admin", body={"technician_id": "TEC-01"}, claims={"cognito:username": "u-a"})
    assert service.run(ev, make_deps(incident()))["statusCode"] == 200


def test_f20_reason_demasiado_largo_o_no_texto_400():
    for reason in ("x" * 501, 123, ["a"]):
        resp = service.run(make_event(ACK, body={"decision": "accept", "reason": reason}), make_deps(incident()))
        assert resp["statusCode"] == 400
    resp = service.run(
        make_event(ASSIGN, groups="supervisor", body={"technician_id": "TEC-01", "reason": "x" * 501}),
        make_deps(incident()),
    )
    assert resp["statusCode"] == 400


def test_f20_components_replaced_limites_400():
    deps = make_deps(incident("in_progress"))
    for comps in (["C"] * 51, [1], "CMP-1", ["x" * 65]):
        resp = service.run(make_event(RESOLVE, body={"resolution_notes": "ok", "components_replaced": comps}), deps)
        assert resp["statusCode"] == 400
    ok = service.run(make_event(RESOLVE, body={"resolution_notes": "ok", "components_replaced": ["C"] * 50}), deps)
    assert ok["statusCode"] == 200


def test_f37_cost_usd_no_finito_400():
    deps = make_deps(incident("in_progress"))
    for raw in ('{"resolution_notes":"ok","cost_usd":NaN}', '{"resolution_notes":"ok","cost_usd":Infinity}'):
        ev = make_event(RESOLVE)
        ev["body"] = raw
        assert service.run(ev, deps)["statusCode"] == 400
    ev = make_event(RESOLVE, body={"resolution_notes": "ok", "cost_usd": -1})
    assert service.run(ev, deps)["statusCode"] == 400


def test_f37_bridge_data_no_dict_400_y_event_id_invalido_400():
    deps = make_deps(incident())
    assert service.run(bridge({**BRIDGE_ACK, "data": [1, 2]}), deps)["statusCode"] == 400
    assert service.run(bridge({**BRIDGE_ACK, "data": "x"}), deps)["statusCode"] == 400
    for bad in ("e" * 129, "con espacio", "a/b", 123, ["x"]):
        assert service.run(bridge({**BRIDGE_ACK, "event_id": bad}), deps)["statusCode"] == 400
    assert deps["sfn"].calls == []


def test_f21_bridge_409_libera_idempotencia_para_reintentar():
    inc = incident()
    del inc["ack_token"]  # el token aún no se guardó
    deps = make_deps(inc)
    assert service.run(bridge(BRIDGE_ACK), deps)["statusCode"] == 409
    assert deps["idempotency"].deleted == [{"pk": "BRG#fs-9f3a1"}]
    deps["incidents"].items[("INC#INC-1", "META")]["ack_token"] = "TOKEN-ACK"
    assert service.run(bridge(BRIDGE_ACK), deps)["statusCode"] == 200


def test_f21_bridge_403_no_libera_idempotencia():
    deps = make_deps(incident())
    body = {**BRIDGE_ACK, "event_id": "fs-3", "actor": {"user_id": "u-tec-01", "role": "tecnico"}}
    assert service.run(bridge(body), deps)["statusCode"] == 403
    assert deps["idempotency"].deleted == []


def test_f22_respuesta_normaliza_machine_ids():
    deps = make_deps(incident(machine_id="EX-023"))
    data = body_of(service.run(make_event(ACK, body={"decision": "accept"}), deps))["data"]
    assert data["machine_ids"] == ["EX-023"]


# --------------------------------------------------------------------------- simulador serverless (TAREA-08)
SIM = "/sim/scenario"


def test_sim_tecnico_403():
    resp = service.run(make_event(SIM, body={"scenario": "falla_subita"}), make_deps())
    assert resp["statusCode"] == 403


def test_sim_escenario_invalido_400():
    resp = service.run(make_event(SIM, groups="mantenimiento", body={"scenario": "meteorito"}), make_deps())
    assert resp["statusCode"] == 400
    assert "scenario" in body_of(resp)["error"]["details"][0]["field"]


def test_sim_start_202_escribe_estado_habilitado():
    deps = make_deps()
    resp = service.run(
        make_event(SIM, groups="mantenimiento", body={"scenario": "falla_subita", "duration_min": 5}), deps
    )
    assert resp["statusCode"] == 202
    data = body_of(resp)["data"]
    assert data["enabled"] is True and data["scenario"] == "falla_subita" and data["requested_by"] == "u-sup"
    put = deps["ssm"].puts[0]
    assert put["Name"] == "/arquifusion/dev/sim/state" and put["Overwrite"] is True
    assert json.loads(put["Value"])["enabled"] is True


def test_sim_start_valida_rangos():
    for body in (
        {"scenario": "falla_subita", "duration_min": 0},
        {"scenario": "falla_subita", "duration_min": 31},
        {"scenario": "falla_subita", "interval_s": 4},
        {"scenario": "falla_subita", "speedup": 0},
        {"scenario": "falla_subita", "machines": "CM-004"},
    ):
        resp = service.run(make_event(SIM, groups="admin", body=body), make_deps())
        assert resp["statusCode"] == 400


def test_sim_stop_y_state():
    deps = make_deps()
    deps["ssm"].value = json.dumps({"enabled": True, "scenario": "falla_subita"})
    stop = service.run(make_event("/sim/stop", groups="mantenimiento"), deps)
    assert stop["statusCode"] == 200 and body_of(stop)["data"]["enabled"] is False
    state = service.run(make_event("/sim/state", method="GET", groups="supervisor"), deps)
    assert state["statusCode"] == 200 and body_of(state)["data"]["enabled"] is False


# ---------------------------------------------------------------- Telegram (TAREA-09/10)


def tg_event(update, secret="s3cret"):
    return {
        "httpMethod": "POST",
        "resource": "/telegram/webhook",
        "headers": {"X-Telegram-Bot-Api-Secret-Token": secret},
        "body": json.dumps(update),
        "requestContext": {},
    }


def tg_callback(data="ack:INC-1:accept", chat="-100", update_id=7):
    return {
        "update_id": update_id,
        "callback_query": {
            "id": "cb-1",
            "data": data,
            "message": {"message_id": 55, "chat": {"id": int(chat)}},
            "from": {"id": 999},
        },
    }


def tg_message(text, chat="-100", update_id=8):
    return {"update_id": update_id, "message": {"message_id": 56, "chat": {"id": int(chat)}, "text": text}}


def test_telegram_secret_invalido_401():
    resp = service.run(tg_event(tg_callback(), secret="otro"), make_deps(incident()))
    assert resp["statusCode"] == 401


def test_telegram_chat_no_vinculado_200_sin_ack():
    deps = make_deps(incident())
    resp = service.run(tg_event(tg_callback(chat="-200")), deps)
    assert resp["statusCode"] == 200
    assert not deps["sfn"].calls
    assert "no está vinculado" in deps["telegram_sent"][0][1]["text"]


def test_telegram_callback_ack_usa_claims_del_link_y_quita_botones():
    deps = make_deps(incident())
    resp = service.run(tg_event(tg_callback()), deps)
    assert resp["statusCode"] == 200
    assert body_of(resp)["data"]["action"] == "ack"
    token, output = deps["sfn"].calls[0]
    assert token == "TOKEN-ACK"
    assert output["decision"] == "accept"
    assert output["actor"] == {"type": "user", "user_id": "u-tec-07", "role": "tecnico", "technician_id": "TEC-07"}
    methods = [m for m, _ in deps["telegram_sent"]]
    assert methods == ["answerCallbackQuery", "editMessageReplyMarkup", "sendMessage"]
    assert deps["telegram_sent"][1][1]["reply_markup"] == {"inline_keyboard": []}
    assert "Aceptado por TEC-07" in deps["telegram_sent"][2][1]["text"]


def test_telegram_update_id_repetido_no_ack_dos_veces():
    deps = make_deps(incident())
    ev = tg_event(tg_callback(update_id=42))
    assert service.run(ev, deps)["statusCode"] == 200
    dup = service.run(ev, deps)
    assert body_of(dup)["data"]["duplicate"] is True
    assert len(deps["sfn"].calls) == 1


def test_telegram_estado_lee_la_maquina():
    deps = make_deps(incident())
    resp = service.run(tg_event(tg_message("/estado EX-023")), deps)
    assert resp["statusCode"] == 200
    text = deps["telegram_sent"][-1][1]["text"]
    assert "EX-023" in text and "operational" in text and "91" in text


def test_telegram_resolver_usa_resolve_token():
    deps = make_deps(incident(status="in_progress"))
    resp = service.run(tg_event(tg_message("/resolver INC-1 Cambié el rodamiento")), deps)
    assert resp["statusCode"] == 200
    token, output = deps["sfn"].calls[0]
    assert token == "TOKEN-RES"
    assert output["resolution_notes"] == "Cambié el rodamiento"
