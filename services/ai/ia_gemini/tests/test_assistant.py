import json

import boto3
import pytest
import service
from fakes import TIMEOUT, bedrock, client, converse_reply
from ia_tools import ToolBox
from moto import mock_aws


def api_event(message="¿Qué máquinas están en riesgo?", groups="supervisor", zone="norte", body=None) -> dict:
    return {
        "httpMethod": "POST",
        "headers": {"X-Correlation-Id": "cid-1"},
        "body": json.dumps(body if body is not None else {"message": message, "session_id": "s-1"}),
        "requestContext": {"authorizer": {"claims": {"cognito:groups": groups, "custom:zone": zone}}},
    }


@pytest.fixture
def tables():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        made = {}
        for name in ("machines", "incidents", "insights"):
            made[name] = ddb.create_table(
                TableName=name,
                KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
                AttributeDefinitions=[
                    {"AttributeName": "pk", "AttributeType": "S"},
                    {"AttributeName": "sk", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )
        machines = [
            ("EX-023", "norte", 42, "needs_intervention"),
            ("CM-104", "sur", 35, "operational"),
            ("LD-007", "norte", 90, "operational"),
        ]
        for mid, zone, health, status in machines:
            made["machines"].put_item(
                Item={
                    "pk": f"OP-01#{mid}",
                    "sk": "META",
                    "machine_id": mid,
                    "zone": zone,
                    "health_score": health,
                    "status": status,
                }
            )
        made["incidents"].put_item(
            Item={
                "pk": "INC-1",
                "sk": "META",
                "incident_id": "INC-1",
                "zone": "norte",
                "status": "assigned",
                "severity": "high",
            }
        )
        made["incidents"].put_item(
            Item={
                "pk": "INC-2",
                "sk": "META",
                "incident_id": "INC-2",
                "zone": "norte",
                "status": "closed",
                "severity": "low",
            }
        )
        yield made


def factory(tables):
    return lambda zone: ToolBox(tables["machines"], tables["incidents"], tables["insights"], zone)


def body_of(resp) -> dict:
    return json.loads(resp["body"])


def test_assistant_uses_function_calling(tables):
    call = {
        "candidates": [
            {"content": {"role": "model", "parts": [{"functionCall": {"name": "get_machines_at_risk", "args": {}}}]}}
        ]
    }
    final = {"candidates": [{"content": {"role": "model", "parts": [{"text": "EX-023 está en riesgo."}]}}]}
    gemini, transport = client(call, final)

    resp = service.handle_api(api_event(), gemini, factory(tables))

    data = body_of(resp)["data"]
    assert resp["statusCode"] == 200
    assert data == {
        "answer": "EX-023 está en riesgo.",
        "session_id": "s-1",
        "tools_used": ["get_machines_at_risk"],
        "degraded": False,
    }
    sent = transport.bodies[1]["contents"][-1]["parts"][0]["functionResponse"]["response"]["result"]
    assert [m["machine_id"] for m in sent["machines"]] == ["EX-023"]  # supervisor de norte no ve CM-104


def test_assistant_degrades_without_gemini(tables):
    gemini, _ = client(TIMEOUT)
    resp = service.handle_api(api_event("incidentes abiertos"), gemini, factory(tables))
    data = body_of(resp)["data"]
    assert resp["statusCode"] == 200 and data["degraded"] is True and data["degraded_reason"] == "timeout"
    assert "INC-1" in data["answer"] and "INC-2" not in data["answer"]
    assert data["tools_used"] == ["get_open_incidents"]


def test_global_role_sees_all_zones(tables):
    resp = service.handle_api(api_event("máquinas en riesgo", groups="gerencia"), None, factory(tables))
    answer = body_of(resp)["data"]["answer"]
    assert "EX-023" in answer and "CM-104" in answer


def test_machine_detail_by_id(tables):
    resp = service.handle_api(api_event("¿Cómo está la ex-023?", groups="admin"), None, factory(tables))
    assert "EX-023" in body_of(resp)["data"]["answer"]


def test_operator_is_forbidden(tables):
    resp = service.handle_api(api_event(groups="operador"), None, factory(tables))
    assert resp["statusCode"] == 403 and body_of(resp)["error"]["code"] == "FORBIDDEN"
    assert body_of(resp)["correlation_id"] == "cid-1"


@pytest.mark.parametrize("body", [{}, {"message": "   "}, {"message": "x" * 1001}])
def test_validation_errors(tables, body):
    resp = service.handle_api(api_event(body=body), None, factory(tables))
    assert resp["statusCode"] == 400 and body_of(resp)["error"]["code"] == "VALIDATION_ERROR"


def test_insight_tool_filters_zone(tables):
    tables["insights"].put_item(
        Item={
            "pk": "fuel#7d",
            "sk": "LATEST",
            "generated_at": "2026-11-14T05:00:00Z",
            "data": [{"machine_id": "EX-023", "zone": "norte"}, {"machine_id": "CM-104", "zone": "sur"}],
        }
    )
    out = ToolBox(tables["machines"], tables["incidents"], tables["insights"], "norte").get_insight("fuel#7d")
    assert [r["machine_id"] for r in out["data"]] == ["EX-023"]


def test_unknown_tool_returns_error(tables):
    assert "error" in factory(tables)(None).call("drop_table", {})


def test_is_api_event():
    assert service.is_api_event(api_event()) and not service.is_api_event({"task": "diagnose"})


def test_degraded_reason_secret_missing_sin_filtrar_la_llave(tables):
    from gemini_client import GeminiClient

    def no_key():
        raise RuntimeError("AIzaSECRETO")

    resp = service.handle_api(api_event("incidentes abiertos"), GeminiClient(api_key_provider=no_key), factory(tables))
    data = body_of(resp)["data"]
    assert data["degraded"] is True and data["degraded_reason"] == "secret_missing"
    assert "AIza" not in resp["body"]


def test_respuesta_normal_sin_degraded_reason(tables):
    final = {"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}}]}
    gemini, _ = client(final)
    data = body_of(service.handle_api(api_event(), gemini, factory(tables)))["data"]
    assert data["degraded"] is False and "degraded_reason" not in data


def test_f11_supervisor_sin_zona_403(tables):
    ev = api_event()
    ev["requestContext"]["authorizer"]["claims"].pop("custom:zone")
    assert service.handle_api(ev, None, factory(tables))["statusCode"] == 403
    ev["requestContext"]["authorizer"]["claims"]["custom:zone"] = "*"
    assert service.handle_api(ev, None, factory(tables))["statusCode"] == 200


def test_f37_session_id_invalido_400(tables):
    for sid in ("s" * 65, 123, "con espacio", ["x"]):
        ev = api_event(body={"message": "hola", "session_id": sid})
        assert service.handle_api(ev, None, factory(tables))["statusCode"] == 400
def test_assistant_with_bedrock_tool_use(tables):
    llm, stubber = bedrock()
    stubber.add_response(
        "converse",
        converse_reply(
            {"toolUse": {"toolUseId": "tu-1", "name": "get_open_incidents", "input": {"zone": "norte"}}},
            stop="tool_use",
        ),
    )
    stubber.add_response("converse", converse_reply({"text": "Hay 1 incidente abierto: INC-1."}))

    resp = service.handle_api(api_event("incidentes abiertos"), llm, factory(tables))

    data = body_of(resp)["data"]
    assert data["degraded"] is False and data["tools_used"] == ["get_open_incidents"]
    assert data["answer"] == "Hay 1 incidente abierto: INC-1."
    stubber.assert_no_pending_responses()


def test_bedrock_tool_result_message_shape():
    from bedrock_client import _to_messages
    from llm_client import LLMTurn, ToolCall

    call = ToolCall(name="get_insight", args={"kind": "fuel#7d"}, id="tu-9")
    turn = LLMTurn(tool_calls=[call], raw=[{"toolUse": {"toolUseId": "tu-9", "name": "get_insight", "input": {}}}])
    msgs = _to_messages(
        [
            {"role": "user", "text": "hola"},
            {"role": "assistant", "turn": turn},
            {"role": "tool", "results": [(call, {"error": "x"})]},
        ]
    )
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    result = msgs[2]["content"][0]["toolResult"]
    assert (
        result["toolUseId"] == "tu-9"
        and result["status"] == "error"
        and result["content"] == [{"json": {"error": "x"}}]
    )


class SlowLLM:
    """LLM que siempre pide otra función: obliga a agotar el deadline global."""

    provider, model, timeout_s = "fake", "fake", 12.0

    def __init__(self):
        self.timeouts = []

    def chat(self, *, history, system, tools, timeout_s=None):
        from llm_client import LLMTurn, ToolCall

        self.timeouts.append(timeout_s)
        return LLMTurn(tool_calls=[ToolCall(name="get_open_incidents", args={})], raw=[])


def test_assistant_respects_global_deadline(tables, monkeypatch):
    import ia_assistant

    clock = iter([0.0, 0.0, 10.0, 19.0])  # deadline = 20: rondas con 20 y 10 s restantes; la 3.a queda con 1 s
    monkeypatch.setattr(ia_assistant.time, "monotonic", lambda: next(clock))
    llm = SlowLLM()
    with pytest.raises(ia_assistant.LLMError):
        ia_assistant.answer_with_llm("hola", llm, factory(tables)(None), "s", budget_s=20)
    assert llm.timeouts == [20.0, 10.0]


def test_assistant_degrades_when_deadline_exhausted(tables, monkeypatch):
    import ia_assistant

    monkeypatch.setattr(ia_assistant, "TOTAL_BUDGET_S", 0.5)
    resp = service.handle_api(api_event("incidentes abiertos"), SlowLLM(), factory(tables))
    assert body_of(resp)["data"]["degraded"] is True
