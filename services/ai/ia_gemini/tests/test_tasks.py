import json
from pathlib import Path

import pytest
import service
from fakes import HTTP_503, TIMEOUT, client, json_reply

FIXTURES = Path(__file__).parents[4] / "contracts/fixtures/ia"
DIAGNOSE = json.loads((FIXTURES / "diagnose_request.json").read_text())


def diagnose_event(**payload_overrides) -> dict:
    return {**DIAGNOSE, "payload": {**DIAGNOSE["payload"], **payload_overrides}}


def test_diagnose_with_gemini_matches_contract():
    expected = json.loads((FIXTURES / "diagnose_response.json").read_text())
    gemini, transport = client(json_reply(expected["result"]))
    out = service.handle_task(diagnose_event(candidate_parts=[{"component_id": "CMP-014"}]), gemini)

    assert set(out) == {"result", "model", "degraded", "prompt_version", "latency_ms"}
    assert out["result"] == expected["result"]
    assert out["degraded"] is False and out["model"] == "gemini-2.5-flash"
    assert out["prompt_version"] == "diagnose-v1"
    config = transport.bodies[0]["generationConfig"]
    assert config["responseMimeType"] == "application/json" and "responseSchema" in config


def test_diagnose_drops_parts_not_in_candidates():
    gemini, _ = client(json_reply({**json.loads((FIXTURES / "diagnose_response.json").read_text())["result"]}))
    out = service.handle_task(diagnose_event(candidate_parts=[]), gemini)  # sin candidatos (la fixture sí los trae)
    assert out["result"]["parts_suggested"] == []


@pytest.mark.parametrize(
    "failure",
    [TIMEOUT, HTTP_503, json_reply("esto no es json"), json_reply({"probable_cause": ""}), {"candidates": []}],
)
def test_diagnose_falls_back_on_any_gemini_failure(failure):
    gemini, _ = client(failure)
    out = service.handle_task(diagnose_event(), gemini)
    assert out["degraded"] is True and out["model"] == "fallback"
    assert out["prompt_version"].endswith("+fallback")
    assert "rodamientos" in out["result"]["probable_cause"].lower()  # temperatura + vibración
    assert set(out["result"]) == {"probable_cause", "suggested_action", "confidence", "parts_suggested"}


def test_missing_api_key_falls_back():
    from gemini_client import GeminiClient

    def no_key():
        raise RuntimeError("secreto no existe")

    out = service.handle_task(diagnose_event(), GeminiClient(api_key_provider=no_key))
    assert out["degraded"] is True


def test_summarize_by_role_builds_schema_per_role():
    roles = ["tecnico", "gerencia"]
    reply = {r: {"title": f"t {r}", "body": f"b {r}"} for r in roles}
    gemini, transport = client(json_reply(reply))
    out = service.handle_task({"task": "summarize_by_role", "payload": {"incident": {}, "roles": roles}}, gemini)
    assert out["result"] == reply
    assert set(transport.bodies[0]["generationConfig"]["responseSchema"]["properties"]) == set(roles)


def test_summarize_chat_truncates_long_conversations():
    messages = [{"role": "tecnico", "text": "x" * 2000} for _ in range(300)]
    reply = {
        "summary": "Se cambió el rodamiento",
        "root_cause": None,
        "actions_taken": ["cambio"],
        "parts_replaced": [],
    }
    gemini, transport = client(json_reply(reply))
    out = service.handle_task(
        {"task": "summarize_chat", "payload": {"incident_id": "INC-1", "messages": messages}}, gemini
    )
    prompt = transport.bodies[0]["contents"][0]["parts"][0]["text"]
    assert out["result"]["root_cause"] is None
    assert prompt.count('"role": "tecnico"') == 200 and "x" * 501 not in prompt


@pytest.mark.parametrize(
    "task", ["diagnose", "summarize_by_role", "common_cause", "summarize_chat", "executive_report"]
)
def test_every_fallback_survives_empty_payload(task):
    out = service.handle_task({"task": task, "payload": {}}, None)
    assert out["degraded"] is True and isinstance(out["result"], dict)


def test_common_cause_fallback_uses_dominant_factor():
    incidents = [{"top_factors": [{"variable": "fuel_rate_lph"}]} for _ in range(3)]
    out = service.handle_task({"task": "common_cause", "payload": {"zone": "norte", "incidents": incidents}}, None)
    assert "combustible" in out["result"]["probable_common_cause"].lower()


def test_unknown_task_is_a_programming_error():
    with pytest.raises(ValueError):
        service.handle_task({"task": "adivinar"}, None)
