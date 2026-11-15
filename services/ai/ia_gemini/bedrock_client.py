"""Proveedor LLM: Amazon Bedrock con la API Converse (RF-02.6, RF-14). Implementa `llm_client.LLMClient`.

Se activa con `LLM_PROVIDER=bedrock` y `BEDROCK_MODEL_ID` (default Amazon Nova Micro: el más barato y rápido,
pago por token, sin costo fijo, RNF serverless). En el AWS Academy Learner Lab el LabRole recibe AccessDenied
en los modelos vigentes, por eso allí el proveedor activo es Gemini; en una cuenta AWS normal basta con cambiar
la variable (y habilitar el acceso al modelo en la consola de Bedrock).

- Salida estructurada: herramienta forzada `respond` cuyo `inputSchema` es el esquema de la tarea
  (`toolChoice.tool`). Si el modelo no la usa, se intenta leer JSON del texto.
- Function calling del asistente: `toolConfig.tools[].toolSpec` + bloques `toolUse` / `toolResult`.
- boto3 viene en el runtime python3.12 de Lambda: no se empaqueta. Timeouts con botocore `Config` y sin
  reintentos (max_attempts=1): una falla cae rápido al fallback determinista.
"""

import json
from collections.abc import Callable

from llm_client import DEFAULT_TIMEOUT_S, LLMError, LLMTurn, ToolCall, to_json_schema

DEFAULT_MODEL_ID = "amazon.nova-micro-v1:0"
CONNECT_TIMEOUT_S = 3.0
MAX_TOKENS = 1024
JSON_TOOL = "respond"

ClientFactory = Callable[[float], object]  # read_timeout_s -> cliente boto3 `bedrock-runtime`


def boto3_client_factory(read_timeout_s: float):
    import boto3
    from botocore.config import Config

    config = Config(
        connect_timeout=min(CONNECT_TIMEOUT_S, read_timeout_s),
        read_timeout=read_timeout_s,
        retries={"max_attempts": 1, "mode": "standard"},
    )
    return boto3.client("bedrock-runtime", config=config)


class BedrockError(LLMError):
    """Falla al obtener una respuesta útil de Bedrock (AccessDenied, throttling, timeout, formato)."""


class BedrockClient:
    provider = "bedrock"

    def __init__(
        self,
        model: str = DEFAULT_MODEL_ID,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        client_factory: ClientFactory = boto3_client_factory,
    ):
        self.model = model
        self.timeout_s = timeout_s
        self._factory = client_factory
        self._clients: dict[int, object] = {}

    def _client(self, timeout_s: float):
        """Cliente boto3 con `read_timeout` = timeout pedido (redondeado a segundos y cacheado por contenedor)."""
        seconds = max(1, int(min(timeout_s or self.timeout_s, self.timeout_s)))
        if seconds not in self._clients:
            self._clients[seconds] = self._factory(float(seconds))
        return self._clients[seconds]

    def _converse(self, timeout_s: float | None, **request) -> dict:
        try:
            client = self._client(timeout_s or self.timeout_s)
            resp = client.converse(
                modelId=self.model,
                inferenceConfig={"temperature": 0.2, "maxTokens": MAX_TOKENS},
                **request,
            )
        except LLMError:
            raise
        except Exception as exc:  # ClientError (AccessDenied, Throttling), timeouts de botocore, credenciales
            raise BedrockError(f"Bedrock no respondió: {type(exc).__name__}: {exc}") from exc
        content = ((resp.get("output") or {}).get("message") or {}).get("content") or []
        if not content:
            raise BedrockError(f"Bedrock no devolvió contenido (stopReason={resp.get('stopReason')})")
        return {"content": content, "stop_reason": resp.get("stopReason")}

    def generate_json(self, *, prompt: str, system: str, schema: dict, timeout_s: float | None = None) -> dict:
        """Salida estructurada vía herramienta forzada `respond` con `inputSchema` = esquema de la tarea."""
        tool = {
            "toolSpec": {
                "name": JSON_TOOL,
                "description": "Entrega la respuesta final con exactamente los campos del esquema.",
                "inputSchema": {"json": to_json_schema(schema)},
            }
        }
        out = self._converse(
            timeout_s,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            system=[{"text": f"{system}\nResponde llamando a la herramienta `{JSON_TOOL}`; no escribas texto libre."}],
            toolConfig={"tools": [tool], "toolChoice": {"tool": {"name": JSON_TOOL}}},
        )
        for block in out["content"]:
            tool_use = block.get("toolUse")
            if tool_use and tool_use.get("name") == JSON_TOOL:
                data = tool_use.get("input")
                if isinstance(data, dict):
                    return data
                raise BedrockError("Bedrock devolvió un JSON que no es objeto")
        return _json_from_text("".join(b.get("text", "") for b in out["content"]))

    def chat(self, *, history: list[dict], system: str, tools: list[dict], timeout_s: float | None = None) -> LLMTurn:
        """Una ronda del asistente: herramientas en `toolConfig`, `toolChoice` automático."""
        specs = [
            {
                "toolSpec": {
                    "name": t["name"],
                    "description": t.get("description", t["name"]),
                    "inputSchema": {
                        "json": to_json_schema(t.get("parameters") or {"type": "OBJECT", "properties": {}})
                    },
                }
            }
            for t in tools
        ]
        out = self._converse(
            timeout_s,
            messages=_to_messages(history),
            system=[{"text": system}],
            toolConfig={"tools": specs, "toolChoice": {"auto": {}}},
        )
        calls = [
            ToolCall(name=b["toolUse"]["name"], args=b["toolUse"].get("input") or {}, id=b["toolUse"].get("toolUseId"))
            for b in out["content"]
            if "toolUse" in b
        ]
        text = "".join(b.get("text", "") for b in out["content"]).strip()
        return LLMTurn(text=text, tool_calls=calls, raw=out["content"])


def _json_from_text(text: str) -> dict:
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    try:
        data = json.loads(cleaned[start : end + 1] if start >= 0 and end > start else cleaned)
    except ValueError as exc:
        raise BedrockError("Bedrock devolvió JSON inválido") from exc
    if not isinstance(data, dict):
        raise BedrockError("Bedrock devolvió un JSON que no es objeto")
    return data


def _to_messages(history: list[dict]) -> list[dict]:
    messages: list[dict] = []
    for item in history:
        if item["role"] == "user":
            messages.append({"role": "user", "content": [{"text": item["text"]}]})
        elif item["role"] == "assistant":
            messages.append({"role": "assistant", "content": item["turn"].raw})
        elif item["role"] == "tool":
            content = [
                {
                    "toolResult": {
                        "toolUseId": call.id or call.name,
                        "content": [{"json": result if isinstance(result, dict) else {"result": result}}],
                        "status": "error" if isinstance(result, dict) and "error" in result else "success",
                    }
                }
                for call, result in item["results"]
            ]
            messages.append({"role": "user", "content": content})
    return messages
