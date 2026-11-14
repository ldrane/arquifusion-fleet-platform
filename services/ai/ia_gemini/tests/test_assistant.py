import json

import boto3
import pytest
import service
from fakes import TIMEOUT, client
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
    assert resp["statusCode"] == 200 and data["degraded"] is True
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
