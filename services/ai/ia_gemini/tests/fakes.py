"""Dobles de prueba para los proveedores LLM (Gemini por transport, Bedrock con botocore Stubber)."""

import json

from gemini_client import GeminiClient, GeminiError


def json_reply(data) -> dict:
    """Respuesta HTTP de Gemini cuyo texto es `data` serializado."""
    text = data if isinstance(data, str) else json.dumps(data)
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}]}


class ScriptedTransport:
    """Devuelve respuestas en orden y registra los cuerpos enviados. Una excepción en la lista se lanza."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.bodies: list[dict] = []
        self.headers: list[dict] = []

    def __call__(self, url, headers, body, timeout_s):
        self.bodies.append(body)
        self.headers.append(headers)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def client(*replies) -> tuple[GeminiClient, ScriptedTransport]:
    transport = ScriptedTransport(*replies)
    return GeminiClient(api_key_provider=lambda: "test-key", transport=transport), transport


TIMEOUT = GeminiError("Gemini no respondió: timed out", "timeout")
HTTP_503 = GeminiError("HTTP 503 de Gemini")


def bedrock(model="amazon.nova-micro-v1:0"):
    """BedrockClient con un cliente boto3 real envuelto en Stubber (valida los parámetros contra el modelo)."""
    import boto3
    from bedrock_client import BedrockClient
    from botocore.stub import Stubber

    raw = boto3.client("bedrock-runtime", region_name="us-east-1")
    stubber = Stubber(raw)
    stubber.activate()
    return BedrockClient(model=model, client_factory=lambda _t: raw), stubber


def converse_reply(*content, stop="end_turn") -> dict:
    return {
        "output": {"message": {"role": "assistant", "content": list(content)}},
        "stopReason": stop,
        "usage": {"inputTokens": 1, "outputTokens": 1, "totalTokens": 2},
        "metrics": {"latencyMs": 1},
    }
