"""Proveedor LLM: Gemini API de Google AI Studio por REST (RF-02.6, RF-14). Implementa `llm_client.LLMClient`.

Sin SDK: usa urllib de la librería estándar para mantener el zip pequeño. Cualquier falla (red, timeout,
HTTP, respuesta bloqueada o JSON inválido) se convierte en GeminiError (subclase de LLMError) para que el
llamador use el fallback.
"""

import json
import os
import socket
import urllib.error
import urllib.request
from collections.abc import Callable

from llm_client import DEFAULT_TIMEOUT_S, LLMError, LLMTurn, ToolCall

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Alias estable de la familia flash-lite (baja latencia, sin pensamiento por defecto): sobrevive a las
# retiradas de versiones fijas (p. ej. 2.5-flash: "no longer available to new users"). Se cambia con GEMINI_MODEL.
DEFAULT_MODEL = "gemini-flash-lite-latest"

Transport = Callable[[str, dict, dict, float], dict]

# Enum público de `degraded_reason` (openapi.yaml / contratos.md). Nunca incluye llaves ni texto de excepciones.
DEGRADED_REASONS = ("secret_missing", "http_4xx", "timeout", "model_not_found", "other")


class GeminiError(LLMError):
    """Falla al obtener una respuesta útil de Gemini. `reason` ∈ DEGRADED_REASONS."""

    def __init__(self, message: str = "", reason: str = "other"):
        super().__init__(message)
        self.reason = reason if reason in DEGRADED_REASONS else "other"


def degraded_reason(exc: BaseException) -> str:
    """Motivo seguro (enum) de una falla de la IA; cualquier excepción sin `reason` válido es `other`."""
    reason = getattr(exc, "reason", None)
    return reason if reason in DEGRADED_REASONS else "other"



def urllib_transport(url: str, headers: dict, body: dict, timeout_s: float) -> dict:
    """POST JSON con timeout. Devuelve el cuerpo decodificado o lanza GeminiError."""
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:  # noqa: S310 (URL fija https)
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
 if exc.code == 404:
            reason = "model_not_found"
        elif 400 <= exc.code < 500:  # key inválida (400/403), cuota (429), etc.
            reason = "http_4xx"
        else:
            reason = "other"
        detail = ""
        try:
            detail = exc.read().decode(errors="replace")[:300]
        except Exception:  # noqa: BLE001 (el detalle es opcional)
            pass
        raise GeminiError(f"HTTP {exc.code} de Gemini {detail}".strip(), reason) from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        timed_out = isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(
            getattr(exc, "reason", None), (TimeoutError, socket.timeout)
        )
        raise GeminiError(f"Gemini no respondió: {exc}", "timeout" if timed_out else "other") from exc

def thinking_config(model: str) -> dict | None:
    """`thinkingConfig` solo donde se sabe que aplica: la familia 2.5 flash acepta `thinkingBudget: 0` (latencia
    mínima). 2.5 pro no permite desactivarlo, y los alias `*-latest` / Gemini 3 usan sus propios valores por
    defecto: a esos no se les envía nada para no provocar un 400."""
    name = model.lower()
    if name.startswith("gemini-2.5") and "pro" not in name:
        return {"thinkingBudget": 0}
    return None


class GeminiClient:
    """Cliente de `generateContent` con salida JSON estructurada y function calling."""

    provider = "gemini"

    def __init__(
        self,
        api_key_provider: Callable[[], str],
        model: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport: Transport = urllib_transport,
    ):
        self.model = model or default_model()
        self.timeout_s = timeout_s
        self._api_key_provider = api_key_provider
        self._transport = transport

    def generate(
        self,
        *,
        contents: list[dict],
        system: str | None = None,
        response_schema: dict | None = None,
        tools: list[dict] | None = None,
        timeout_s: float | None = None,
    ) -> dict:
        """Llama a Gemini y devuelve el `content` del primer candidato (`{"role": "model", "parts": [...]}`)."""
        generation_config: dict = {"temperature": 0.2}
        thinking = thinking_config(self.model)
        if thinking:
            generation_config["thinkingConfig"] = thinking
        if response_schema:
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = response_schema
        body: dict = {"contents": contents, "generationConfig": generation_config}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            body["tools"] = [{"functionDeclarations": tools}]

        try:
            headers = {"Content-Type": "application/json", "x-goog-api-key": self._api_key_provider()}
        except Exception as exc:  # el secreto no está disponible: se trata como falla de Gemini
            raise GeminiError("API key de Gemini no disponible", "secret_missing") from exc

        timeout = min(timeout_s or self.timeout_s, self.timeout_s)
        try:
            raw = self._transport(API_URL.format(model=self.model), headers, body, timeout)
        except LLMError:
            raise
        except Exception as exc:  # transporte inesperado: igual cae al fallback
            raise GeminiError(f"Gemini no respondió: {exc}") from exc
        candidates = raw.get("candidates") or [] if isinstance(raw, dict) else []
        content = candidates[0].get("content") if candidates else None
        if not content or not content.get("parts"):
            raise GeminiError("Gemini no devolvió contenido (posible bloqueo de seguridad)")
        return content

    def generate_json(self, *, prompt: str, system: str, schema: dict, timeout_s: float | None = None) -> dict:
        """Pide una respuesta JSON que cumpla `schema` y la devuelve como dict."""
        content = self.generate(
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            system=system,
            response_schema=schema,
            timeout_s=timeout_s,
        )
        text = "".join(part.get("text", "") for part in content["parts"] if not part.get("thought"))
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise GeminiError("Gemini devolvió JSON inválido") from exc
        if not isinstance(data, dict):
            raise GeminiError("Gemini devolvió un JSON que no es objeto")
        return data

    def chat(self, *, history: list[dict], system: str, tools: list[dict], timeout_s: float | None = None) -> LLMTurn:
        """Una ronda del asistente con function calling sobre el historial neutral (ver llm_client)."""
        content = self.generate(contents=_to_contents(history), system=system, tools=tools, timeout_s=timeout_s)
        parts = content["parts"]
        calls = [
            ToolCall(
                name=p["functionCall"]["name"], args=p["functionCall"].get("args") or {}, id=p["functionCall"].get("id")
            )
            for p in parts
            if "functionCall" in p
        ]
        text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        return LLMTurn(text=text, tool_calls=calls, raw=parts)


def _to_contents(history: list[dict]) -> list[dict]:
    contents: list[dict] = []
    for item in history:
        if item["role"] == "user":
            contents.append({"role": "user", "parts": [{"text": item["text"]}]})
        elif item["role"] == "assistant":
            contents.append({"role": "model", "parts": item["turn"].raw})  # incluye thoughtSignature si viene
        elif item["role"] == "tool":
            parts = []
            for call, result in item["results"]:
                response = {"name": call.name, "response": {"result": result}}
                if call.id:
                    response["id"] = call.id
                parts.append({"functionResponse": response})
            contents.append({"role": "user", "parts": parts})
    return contents
