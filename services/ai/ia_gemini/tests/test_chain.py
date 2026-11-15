"""Cadena de proveedores LLM (TAREA-06): gemini → bedrock → determinista."""

import json
from pathlib import Path

import pytest
import service
from fakes import json_reply
from llm_client import LLMError, build_clients

FIXTURES = Path(__file__).parents[4] / "contracts/fixtures/ia"
DIAGNOSE = json.loads((FIXTURES / "diagnose_request.json").read_text())
DIAGNOSE_RESULT = json.loads((FIXTURES / "diagnose_response.json").read_text())["result"]


class FakeLLM:
    """Proveedor mínimo: responde o lanza `LLMError` en `generate_json`."""

    def __init__(self, provider: str, *, result: dict | None = None, error: Exception | None = None, model="fake"):
        self.provider = provider
        self.model = model
        self.timeout_s = 12.0
        self.endpoint = "aistudio" if provider == "gemini" else None
        self._result = result
        self._error = error
        self.calls = 0

    def generate_json(self, *, prompt, system, schema, timeout_s=None):
        self.calls += 1
        if self._error:
            raise self._error
        return self._result

    def chat(self, *, history, system, tools, timeout_s=None):
        raise AssertionError("no usado")


def test_second_provider_wins_when_the_first_fails():
    first = FakeLLM("gemini", error=LLMError("caído"))
    second = FakeLLM("bedrock", result=DIAGNOSE_RESULT, model="nova")
    out = service.handle_task(DIAGNOSE, [first, second])
    assert out["degraded"] is False and out["provider"] == "bedrock" and out["model"] == "nova"
    assert out["result"]["probable_cause"] == DIAGNOSE_RESULT["probable_cause"]
    assert first.calls == 1 and second.calls == 1


def test_all_providers_fail_uses_fallback_and_first_reason():
    from gemini_client import GeminiError

    first = FakeLLM("gemini", error=GeminiError("timeout", "timeout"))
    second = FakeLLM("bedrock", error=LLMError("denied"))
    out = service.handle_task(DIAGNOSE, [first, second])
    assert out["degraded"] is True and out["provider"] == "fallback" and out["model"] == "fallback"
    assert out["degraded_reason"] == "timeout"


def test_single_client_keeps_previous_behaviour():
    only = FakeLLM("gemini", result=DIAGNOSE_RESULT, model="gemini-x")
    out = service.handle_task(DIAGNOSE, only)
    assert out["degraded"] is False and out["provider"] == "gemini" and out["endpoint"] == "aistudio"


def test_build_clients_order_and_dedupe():
    llms = build_clients({"LLM_PROVIDER": "gemini, bedrock,gemini"}, gemini_api_key_provider=lambda: "k")
    assert [llm.provider for llm in llms] == ["gemini", "bedrock"]
    assert build_clients({"LLM_PROVIDER": ""}, gemini_api_key_provider=lambda: "k")[0].provider == "gemini"
    with pytest.raises(ValueError):
        build_clients({"LLM_PROVIDER": "gemini,openai"}, gemini_api_key_provider=lambda: "k")


def test_transport_fake_still_returns_json():
    """El doble de transporte sigue siendo compatible con la cadena (sin proveedores reales)."""
    from fakes import client

    gemini, _ = client(json_reply(DIAGNOSE_RESULT))
    out = service.handle_task(DIAGNOSE, [gemini])
    assert out["provider"] == "gemini" and out["degraded"] is False
