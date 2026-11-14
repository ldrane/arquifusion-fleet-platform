"""Cliente REST mínimo de la Gemini API de Google AI Studio (RF-02.6, RF-14).

Sin SDK: usa urllib de la librería estándar para mantener el zip pequeño. Cualquier falla (red, timeout,
HTTP, respuesta bloqueada o JSON inválido) se convierte en GeminiError para que el llamador use el fallback.
"""

import json
import os
import socket
import urllib.error
import urllib.request
from collections.abc import Callable

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Única fuente del modelo: env GEMINI_MODEL (lo fija infra/ingest/ai.tf) con este default.
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_TIMEOUT_S = 8.0

Transport = Callable[[str, dict, dict, float], dict]


# Enum público de `degraded_reason` (openapi.yaml / contratos.md). Nunca incluye llaves ni texto de excepciones.
DEGRADED_REASONS = ("secret_missing", "http_4xx", "timeout", "model_not_found", "other")


class GeminiError(Exception):
    """Falla al obtener una respuesta útil de Gemini. `reason` ∈ DEGRADED_REASONS."""

    def __init__(self, message: str = "", reason: str = "other"):
        super().__init__(message)
        self.reason = reason if reason in DEGRADED_REASONS else "other"


def degraded_reason(exc: BaseException) -> str:
    """Motivo seguro (enum) de una falla de la IA; cualquier excepción ajena a GeminiError es `other`."""
    reason = getattr(exc, "reason", None) if isinstance(exc, GeminiError) else None
    return reason if reason in DEGRADED_REASONS else "other"


def default_model() -> str:
    return os.environ.get("GEMINI_MODEL") or DEFAULT_MODEL


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
        raise GeminiError(f"HTTP {exc.code} de Gemini", reason) from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        timed_out = isinstance(exc, (TimeoutError, socket.timeout)) or isinstance(
            getattr(exc, "reason", None), (TimeoutError, socket.timeout)
        )
        raise GeminiError(f"Gemini no respondió: {exc}", "timeout" if timed_out else "other") from exc


class GeminiClient:
    """Cliente de `generateContent` con salida JSON estructurada y function calling."""

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
        generation_config: dict = {"temperature": 0.2, "thinkingConfig": {"thinkingBudget": 0}}
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
        raw = self._transport(API_URL.format(model=self.model), headers, body, timeout)
        candidates = raw.get("candidates") or []
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
        text = "".join(part.get("text", "") for part in content["parts"])
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise GeminiError("Gemini devolvió JSON inválido") from exc
        if not isinstance(data, dict):
            raise GeminiError("Gemini devolvió un JSON que no es objeto")
        return data
