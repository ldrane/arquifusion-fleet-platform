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


@pytest.mark.parametrize(
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


# ---------------------------------------------------------------- TAREA-05: AI Studio / Vertex express
@pytest.fixture(autouse=True)
def _reset_resolved_base(monkeypatch):
    import gemini_client

    monkeypatch.delenv("GEMINI_API_BASE", raising=False)
    monkeypatch.delenv("GEMINI_VERTEX_MODEL", raising=False)
    gemini_client._RESOLVED_BASE = None
    yield
    gemini_client._RESOLVED_BASE = None


def test_auto_falls_back_to_vertex_and_remembers_it():
    from gemini_client import VERTEX_URL

    denied = GeminiError("HTTP 403 de Gemini", "http_4xx", status=403)
    gemini, transport = client(denied, json_reply({"ok": True}), json_reply({"ok": True}))
    assert gemini.generate_json(prompt="p", system="s", schema={}) == {"ok": True}
    assert gemini.endpoint == "vertex"
    assert gemini.model == "gemini-2.5-flash-lite"
    assert len(transport.bodies) == 2 and transport.urls[1].startswith(VERTEX_URL.split("/{model}")[0])
    # La segunda llamada va directo a Vertex (no reintenta AI Studio).
    assert gemini.generate_json(prompt="p", system="s", schema={}) == {"ok": True}
    assert len(transport.bodies) == 3
    assert transport.urls[2].startswith(VERTEX_URL.split("/{model}")[0])


def test_quota_does_not_fall_back_to_vertex():
    from gemini_client import AISTUDIO_URL

    quota = GeminiError("HTTP 429 de Gemini", "http_4xx", status=429)
    gemini, transport = client(quota)
    with pytest.raises(GeminiError) as exc:
        gemini.generate_json(prompt="p", system="s", schema={})
    assert exc.value.reason == "http_4xx" and exc.value.status == 429
    assert len(transport.bodies) == 1 and transport.urls[0].startswith(AISTUDIO_URL.split("/{model}")[0])


def test_explicit_vertex_base_only_uses_vertex(monkeypatch):
    from gemini_client import VERTEX_URL

    monkeypatch.setenv("GEMINI_API_BASE", "vertex")
    monkeypatch.setenv("GEMINI_VERTEX_MODEL", "gemini-2.5-flash")
    gemini, transport = client(json_reply({"ok": True}))
    gemini.generate_json(prompt="p", system="s", schema={})
    assert gemini.endpoint == "vertex" and gemini.model == "gemini-2.5-flash"
    assert len(transport.urls) == 1 and transport.urls[0].startswith(VERTEX_URL.split("/{model}")[0])
    assert transport.headers[0]["x-goog-api-key"] == "test-key"
