"""Dobles de prueba para el cliente Gemini."""

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


TIMEOUT = GeminiError("Gemini no respondió: timed out")
HTTP_503 = GeminiError("HTTP 503 de Gemini")
