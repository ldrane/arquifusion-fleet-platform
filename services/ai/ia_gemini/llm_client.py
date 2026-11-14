"""Capa de abstracción del proveedor LLM de `ia-gemini` (RF-02.6, RF-10.3, RF-12.3, RF-14, RF-16.8, MH-MC-03).

Todo el servicio habla con un `LLMClient`; el proveedor concreto se elige por la variable `LLM_PROVIDER`:
- `gemini` (default): Gemini API de Google AI Studio (`gemini_client.GeminiClient`). Proveedor activo en el Learner Lab.
- `bedrock`: Amazon Bedrock Converse (`bedrock_client.BedrockClient`). Listo para una cuenta AWS sin las SCP del lab.

Contrato común:
- `generate_json(prompt, system, schema, timeout_s)` → dict que cumple `schema` (salida estructurada).
- `chat(history, system, tools, timeout_s)` → `LLMTurn` (texto final o llamadas a funciones) para el asistente.
- Cualquier falla (red, timeout, cuota, permisos, bloqueo, JSON inválido) se lanza como `LLMError`; el llamador
  responde con el fallback determinista (`ia_fallbacks`), nunca propaga el error (MH-MC-03).

Los esquemas (`ia_tasks`) y las declaraciones de funciones (`ia_tools`) se escriben en el dialecto OpenAPI de
Gemini (`"type": "OBJECT"`, `nullable`). `to_json_schema` los traduce a JSON Schema estándar para otros proveedores.

Historial neutral del asistente (lista de dicts, en orden):
- `{"role": "user", "text": str}`
- `{"role": "assistant", "turn": LLMTurn}`  (se reenvía `turn.raw` tal cual: firmas de pensamiento de Gemini, ids)
- `{"role": "tool", "results": [(ToolCall, dict), ...]}`
"""

import os
from dataclasses import dataclass, field
from typing import Protocol

DEFAULT_PROVIDER = "gemini"
DEFAULT_TIMEOUT_S = 12.0  # por llamada; el asistente además respeta un deadline global (ia_assistant)


class LLMError(Exception):
    """Falla al obtener una respuesta útil del proveedor LLM. Siempre lleva al fallback determinista."""


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict
    id: str | None = None  # Bedrock exige `toolUseId`; Gemini puede no traerlo


@dataclass(frozen=True)
class LLMTurn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: object = None  # contenido nativo del proveedor, para reenviarlo en la siguiente ronda


class LLMClient(Protocol):
    provider: str
    model: str
    timeout_s: float

    def generate_json(self, *, prompt: str, system: str, schema: dict, timeout_s: float | None = None) -> dict: ...

    def chat(
        self, *, history: list[dict], system: str, tools: list[dict], timeout_s: float | None = None
    ) -> LLMTurn: ...


def to_json_schema(schema: dict) -> dict:
    """Traduce un esquema estilo Gemini (`OBJECT`, `nullable`) a JSON Schema (`object`, `["string", "null"]`)."""
    if not isinstance(schema, dict):
        return schema
    out: dict = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, str):
            out["type"] = value.lower()
        elif key == "properties" and isinstance(value, dict):
            out["properties"] = {name: to_json_schema(sub) for name, sub in value.items()}
        elif key == "items":
            out["items"] = to_json_schema(value)
        elif key != "nullable":
            out[key] = value
    if schema.get("nullable") and isinstance(out.get("type"), str):
        out["type"] = [out["type"], "null"]
    return out


def build_client(env: dict | None = None, *, gemini_api_key_provider=None) -> LLMClient:
    """Crea el cliente según `LLM_PROVIDER` (gemini|bedrock). Lanza ValueError si el proveedor no existe."""
    env = os.environ if env is None else env
    provider = (env.get("LLM_PROVIDER") or DEFAULT_PROVIDER).strip().lower()
    timeout_s = float(env.get("LLM_TIMEOUT_S") or env.get("GEMINI_TIMEOUT_S") or DEFAULT_TIMEOUT_S)
    if provider == "gemini":
        from gemini_client import DEFAULT_MODEL, GeminiClient

        if gemini_api_key_provider is None:
            raise ValueError("LLM_PROVIDER=gemini requiere un proveedor de API key")
        return GeminiClient(
            api_key_provider=gemini_api_key_provider,
            model=env.get("GEMINI_MODEL") or DEFAULT_MODEL,
            timeout_s=timeout_s,
        )
    if provider == "bedrock":
        from bedrock_client import DEFAULT_MODEL_ID, BedrockClient

        return BedrockClient(model=env.get("BEDROCK_MODEL_ID") or DEFAULT_MODEL_ID, timeout_s=timeout_s)
    raise ValueError(f"LLM_PROVIDER desconocido: {provider!r} (válidos: gemini, bedrock)")
