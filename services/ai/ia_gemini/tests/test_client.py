import urllib.error

import pytest
from fakes import client, json_reply
from gemini_client import GeminiError, urllib_transport


def test_api_key_goes_in_header_and_tools_in_body():
    gemini, transport = client(json_reply({"ok": True}))
    gemini.generate(contents=[], tools=[{"name": "f"}])
    assert transport.headers[0]["x-goog-api-key"] == "test-key"
    assert transport.bodies[0]["tools"] == [{"functionDeclarations": [{"name": "f"}]}]


def test_timeout_never_exceeds_limit():
    seen = []
    gemini, _ = client()
    gemini._transport = lambda url, h, b, timeout: seen.append(timeout) or json_reply({})
    gemini.generate(contents=[], timeout_s=60)
    assert seen == [gemini.timeout_s]


def test_urllib_transport_wraps_http_errors(monkeypatch):
    def boom(*_a, **_k):
        raise urllib.error.HTTPError("u", 429, "quota", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(GeminiError, match="429"):
        urllib_transport("https://x", {}, {}, 1)


def test_non_object_json_is_rejected():
    gemini, _ = client(json_reply([1, 2]))
    with pytest.raises(GeminiError):
        gemini.generate_json(prompt="p", system="s", schema={})


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (urllib.error.HTTPError("u", 429, "quota", {}, None), "http_4xx"),
        (urllib.error.HTTPError("u", 403, "key", {}, None), "http_4xx"),
        (urllib.error.HTTPError("u", 404, "model", {}, None), "model_not_found"),
        (urllib.error.HTTPError("u", 503, "down", {}, None), "other"),
        (TimeoutError("timed out"), "timeout"),
        (urllib.error.URLError(TimeoutError("timed out")), "timeout"),
        (urllib.error.URLError("dns"), "other"),
    ],
)
def test_transport_clasifica_motivo(monkeypatch, exc, reason):
    def boom(*_a, **_k):
        raise exc

    monkeypatch.setattr("urllib.request.urlopen", boom)
    with pytest.raises(GeminiError) as e:
        urllib_transport("https://x", {}, {}, 1)
    assert e.value.reason == reason


def test_modelo_unico_desde_env(monkeypatch):
    from gemini_client import DEFAULT_MODEL, GeminiClient

    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert GeminiClient(api_key_provider=lambda: "k").model == DEFAULT_MODEL
    monkeypatch.setenv("GEMINI_MODEL", "gemini-x")
    assert GeminiClient(api_key_provider=lambda: "k").model == "gemini-x"
    ("model", "expected"),
    [
        ("gemini-2.5-flash-lite", {"thinkingBudget": 0}),
        ("gemini-2.5-flash", {"thinkingBudget": 0}),
        ("gemini-2.5-pro", None),
        ("gemini-flash-lite-latest", None),
        ("gemini-3.8-flash", None),
    ],
)
def test_thinking_config_only_where_supported(model, expected):
    gemini, transport = client(json_reply({}))
    gemini.model = model
    gemini.generate(contents=[])
    assert transport.bodies[0]["generationConfig"].get("thinkingConfig") == expected


def test_gemini_error_is_llm_error():
    from llm_client import LLMError

    assert issubclass(GeminiError, LLMError)


def test_build_client_selects_provider():
    from bedrock_client import BedrockClient
    from gemini_client import GeminiClient
    from llm_client import build_client

    g = build_client({"GEMINI_MODEL": "gemini-x", "LLM_TIMEOUT_S": "13"}, gemini_api_key_provider=lambda: "k")
    assert isinstance(g, GeminiClient) and g.model == "gemini-x" and g.timeout_s == 13.0
    b = build_client({"LLM_PROVIDER": "bedrock", "BEDROCK_MODEL_ID": "amazon.nova-lite-v1:0"})
    assert isinstance(b, BedrockClient) and b.model == "amazon.nova-lite-v1:0" and b.provider == "bedrock"
    with pytest.raises(ValueError):
        build_client({"LLM_PROVIDER": "openai"})


def test_to_json_schema_translates_gemini_dialect():
    from llm_client import to_json_schema

    schema = {
        "type": "OBJECT",
        "properties": {"a": {"type": "STRING", "nullable": True}, "b": {"type": "ARRAY", "items": {"type": "NUMBER"}}},
        "required": ["a"],
    }
    assert to_json_schema(schema) == {
        "type": "object",
        "properties": {"a": {"type": ["string", "null"]}, "b": {"type": "array", "items": {"type": "number"}}},
        "required": ["a"],
    }
