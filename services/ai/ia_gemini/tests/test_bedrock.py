"""Proveedor Bedrock (Converse) con botocore Stubber: salida estructurada, function calling y fallback."""

import pytest
import service
from fakes import bedrock, converse_reply
from llm_client import LLMError

DIAG = {
    "probable_cause": "Falla de rodamientos",
    "suggested_action": "Inspeccionar rodamientos",
    "confidence": 0.8,
    "parts_suggested": ["CMP-014"],
}
PAYLOAD = {
    "top_factors": [{"variable": "temperature_c"}, {"variable": "vibration_mm_s"}],
    "candidate_parts": [{"component_id": "CMP-014", "name": "Kit de rodamientos de motor", "specialty": "motor"}],
}


def test_generate_json_uses_forced_tool_with_json_schema():
    llm, stubber = bedrock()
    stubber.add_response("converse", converse_reply({"toolUse": {"toolUseId": "t1", "name": "respond", "input": DIAG}}))
    out = service.handle_task({"task": "diagnose", "payload": PAYLOAD}, llm)
    stubber.assert_no_pending_responses()
    assert out["degraded"] is False and out["model"] == "amazon.nova-micro-v1:0"
    assert out["result"]["parts_suggested"] == ["CMP-014"]


def test_generate_json_request_shape():
    llm, stubber = bedrock()
    stubber.add_response(
        "converse",
        converse_reply({"toolUse": {"toolUseId": "t1", "name": "respond", "input": {"x": "y"}}}),
        expected_params={
            "modelId": "amazon.nova-micro-v1:0",
            "messages": [{"role": "user", "content": [{"text": "p"}]}],
            "system": [{"text": "s\nResponde llamando a la herramienta `respond`; no escribas texto libre."}],
            "inferenceConfig": {"temperature": 0.2, "maxTokens": 1024},
            "toolConfig": {
                "tools": [
                    {
                        "toolSpec": {
                            "name": "respond",
                            "description": "Entrega la respuesta final con exactamente los campos del esquema.",
                            "inputSchema": {"json": {"type": "object", "properties": {"x": {"type": "string"}}}},
                        }
                    }
                ],
                "toolChoice": {"tool": {"name": "respond"}},
            },
        },
    )
    assert llm.generate_json(
        prompt="p", system="s", schema={"type": "OBJECT", "properties": {"x": {"type": "STRING"}}}
    ) == {"x": "y"}


def test_generate_json_accepts_json_in_text():
    llm, stubber = bedrock()
    stubber.add_response("converse", converse_reply({"text": '```json\n{"summary_text": "ok"}\n```'}))
    assert llm.generate_json(prompt="p", system="s", schema={}) == {"summary_text": "ok"}


@pytest.mark.parametrize("code", ["AccessDeniedException", "ThrottlingException", "ValidationException"])
def test_client_errors_become_llm_error_and_fallback(code):
    llm, stubber = bedrock()
    stubber.add_client_error("converse", service_error_code=code, http_status_code=403)
    with pytest.raises(LLMError, match=code):
        llm.generate_json(prompt="p", system="s", schema={})
    stubber.add_client_error("converse", service_error_code=code, http_status_code=403)
    out = service.handle_task({"task": "diagnose", "payload": PAYLOAD}, llm)
    assert out["degraded"] is True and out["model"] == "fallback"


def test_invalid_text_is_llm_error():
    llm, stubber = bedrock()
    stubber.add_response("converse", converse_reply({"text": "no es json"}))
    with pytest.raises(LLMError):
        llm.generate_json(prompt="p", system="s", schema={})


def test_client_timeout_is_capped_and_cached():
    seen = []
    from bedrock_client import BedrockClient

    llm = BedrockClient(timeout_s=12, client_factory=lambda t: seen.append(t) or object())
    llm._client(60)
    llm._client(12)
    llm._client(5.5)
    assert seen == [12.0, 5.0]
