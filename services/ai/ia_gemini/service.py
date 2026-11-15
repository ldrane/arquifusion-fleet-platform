"""Lógica de `ia-gemini` (RF-02.6, RF-10.1, RF-10.3, RF-12.3, RF-14, RF-16.8).

Dos modos de entrada:
- Invocación directa (Step Functions, otras Lambdas): `{"task", "correlation_id", "payload"}` → contratos.md §8.
- API Gateway (`POST /v1/assistant/chat`): evento proxy con JWT de Cognito → respuesta según openapi.yaml.

El proveedor LLM es configurable (`LLM_PROVIDER`=gemini|bedrock, ver llm_client).
Regla: una falla del LLM nunca se propaga. Se responde con el fallback determinista y `degraded: true`.
"""

import json
import re
import time
import uuid
from collections.abc import Callable

import ia_assistant
import prompts
from arquifusion_shared import correlation, rbac, response
from arquifusion_shared.errors import ApiError, ValidationError
from arquifusion_shared.observability import logger
from ia_tasks import TASKS, payload_json
from ia_tools import ToolBox
from llm_client import LLMClient, LLMError

FALLBACK_MODEL = "fallback"
ASSISTANT_ROLES = ("tecnico", "mantenimiento", "supervisor", "admin", "gerencia")
GLOBAL_ROLES = {"admin", "gerencia", "mantenimiento"}  # ven todas las zonas
MAX_MESSAGE_CHARS = 1000
MAX_SESSION_ID = 64
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._:\-]+$")


def _safe_error(exc: Exception) -> str:
    """Texto apto para logs: mensaje de GeminiError (sin llaves) o solo el nombre de la excepción."""
    return str(exc) if isinstance(exc, GeminiError) else type(exc).__name__


def is_api_event(event: dict) -> bool:
    return "httpMethod" in event and "requestContext" in event


# ---------------------------------------------------------------- invocación directa
def handle_task(event: dict, llm: LLMClient | None) -> dict:
    """Ejecuta una tarea del contrato §8. Solo lanza ValueError si la tarea no existe (error de programación)."""
    task = event.get("task")
    spec = TASKS.get(task)
    if spec is None:
        raise ValueError(f"task desconocida: {task!r}. Válidas: {sorted(TASKS)}")
    payload = event.get("payload") or {}
    prompt = prompts.load(task)
    started = time.monotonic()
    try:
        if llm is None:
            raise LLMError("cliente LLM no configurado")
        if not spec.has_input(payload):
            raise LLMError("sin datos de entrada para el LLM")
        raw = llm.generate_json(
            prompt=prompt.render(payload_json(spec.prepare(payload))),
            system=prompts.load("system").text,
            schema=spec.schema(payload),
        )
        result, model, degraded = spec.normalize(raw, payload), llm.model, False
        reason = None
    except Exception as exc:  # cualquier falla de la IA (red, cuota, JSON, validación) → fallback
        reason = degraded_reason(exc)
        logger.warning(
            "LLM no disponible, se usa fallback",
            extra={
                "task": task,
                "provider": getattr(llm, "provider", None),
                "degraded_reason": reason,
                "error": _safe_error(exc),
            },
        )
        result, model, degraded = spec.fallback(payload), FALLBACK_MODEL, True
    out = {
        "result": result,
        "model": model,
        "degraded": degraded,
        "prompt_version": prompt.version if not degraded else f"{prompt.version}+fallback",
        "latency_ms": int((time.monotonic() - started) * 1000),
    }
    if degraded:
        out["degraded_reason"] = reason
    return out


# ---------------------------------------------------------------- API Gateway: asistente
def _parse_body(event: dict) -> dict:
    try:
        body = json.loads(event.get("body") or "{}")
    except ValueError as exc:
        raise ValidationError("El cuerpo no es JSON válido") from exc
    message = body.get("message") if isinstance(body, dict) else None
    if not isinstance(message, str) or not message.strip():
        raise ValidationError("`message` es obligatorio", [{"field": "message", "issue": "required"}])
    if len(message) > MAX_MESSAGE_CHARS:
        raise ValidationError(
            f"`message` supera {MAX_MESSAGE_CHARS} caracteres", [{"field": "message", "issue": "max_length"}]
        )
    session_id = body.get("session_id")
    if session_id is not None and (
        not isinstance(session_id, str) or len(session_id) > MAX_SESSION_ID or not _SESSION_ID_RE.match(session_id)
    ):
        raise ValidationError(
            f"`session_id` debe ser texto simple de hasta {MAX_SESSION_ID} caracteres",
            [{"field": "session_id", "issue": "invalid"}],
        )
    return {"message": message.strip(), "session_id": session_id or None}


def _zone_scope(event: dict) -> str | None:
    if rbac.groups(event) & GLOBAL_ROLES:
        return None
    return rbac.zone(event)  # F-11: roles de zona sin custom:zone => Forbidden; "*" explícito = global


def handle_api(event: dict, llm: LLMClient | None, tools_factory: Callable[[str | None], ToolBox]) -> dict:
    """`POST /v1/assistant/chat`: responde 200 aunque el LLM falle (`degraded: true`), según el OpenAPI."""
    cid = correlation.from_api_event(event)
    logger.set_correlation_id(cid)
    try:
        rbac.require(event, *ASSISTANT_ROLES)
        body = _parse_body(event)
        tools = tools_factory(_zone_scope(event))
        try:
            if llm is None:
                raise LLMError("cliente LLM no configurado")
            answer, used = ia_assistant.answer_with_llm(body["message"], llm, tools, prompts.load("assistant").text)
            degraded, reason = False, None
        except Exception as exc:  # la IA nunca rompe el endpoint
            reason = degraded_reason(exc)
            logger.warning(
                "Asistente en modo determinista",
                extra={
                    "provider": getattr(llm, "provider", None),
                    "degraded_reason": reason,
                    "error": _safe_error(exc),
                },
            )
            answer, used = ia_assistant.answer_deterministic(body["message"], tools)
            degraded = True
        data = {
            "answer": answer,
            "session_id": body["session_id"] or str(uuid.uuid4()),
            "tools_used": list(dict.fromkeys(used)),
            "degraded": degraded,
        }
        if degraded:
            data["degraded_reason"] = reason
        return response.ok(data, cid)
    except ApiError as err:
        return response.error(err, cid)
    except Exception:
        logger.exception("Error no controlado en el asistente")
        return response.error(ApiError("Error interno"), cid)
