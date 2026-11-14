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
    assert seen == [8.0]


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
