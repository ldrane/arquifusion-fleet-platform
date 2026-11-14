"""Tareas de `ia-gemini` (contratos.md §8): prompt, esquema de salida, normalización y fallback por tarea.

RF-02.6 diagnose · RF-10.1 summarize_by_role · RF-12.3 common_cause · RF-16.8 summarize_chat · RF-10.3 executive_report.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass

import ia_fallbacks

STRING = {"type": "STRING"}
NUMBER = {"type": "NUMBER"}
STRING_LIST = {"type": "ARRAY", "items": STRING}
MAX_CHAT_MESSAGES = 200
MAX_MESSAGE_CHARS = 500


def _obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "OBJECT", "properties": properties, "required": required or list(properties)}


def _clamp01(value) -> float:
    return round(min(max(float(value), 0.0), 1.0), 2)


def _text(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("texto vacío en la respuesta de Gemini")
    return value.strip()


def _str_list(value) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("se esperaba una lista")
    return [str(v).strip() for v in value if str(v).strip()]


@dataclass(frozen=True)
class TaskSpec:
    schema: Callable[[dict], dict]
    prepare: Callable[[dict], dict]  # recorta el payload antes de enviarlo al prompt
    normalize: Callable[[dict, dict], dict]  # valida la respuesta de Gemini; ValueError si no sirve
    fallback: Callable[[dict], dict]


# ---------------------------------------------------------------- diagnose
CANDIDATE_FIELDS = ("component_id", "name", "specialty")


def _prepare_diagnose(payload: dict) -> dict:
    """`candidate_parts[] = {component_id, name, specialty}` (contratos.md §8.1): solo esos campos llegan al prompt."""
    candidates = [
        {k: p[k] for k in CANDIDATE_FIELDS if p.get(k)}
        for p in payload.get("candidate_parts") or []
        if isinstance(p, dict) and p.get("component_id")
    ]
    return {**payload, "candidate_parts": candidates}


def _normalize_diagnose(raw: dict, payload: dict) -> dict:
    allowed = {p.get("component_id") for p in payload.get("candidate_parts") or [] if isinstance(p, dict)}
    parts = [p for p in _str_list(raw.get("parts_suggested", [])) if p in allowed]  # nunca IDs inventados
    return {
        "probable_cause": _text(raw.get("probable_cause")),
        "suggested_action": _text(raw.get("suggested_action")),
        "confidence": _clamp01(raw.get("confidence")),
        "parts_suggested": parts,
    }


# ---------------------------------------------------------------- summarize_by_role
def _roles_schema(payload: dict) -> dict:
    message = _obj({"title": STRING, "body": STRING})
    return _obj({role: message for role in payload.get("roles") or []})


def _normalize_by_role(raw: dict, payload: dict) -> dict:
    out = {}
    for role in payload.get("roles") or []:
        item = raw.get(role)
        if not isinstance(item, dict):
            raise ValueError(f"falta el mensaje para el rol {role}")
        out[role] = {"title": _text(item.get("title"))[:60], "body": _text(item.get("body"))[:280]}
    return out


# ---------------------------------------------------------------- common_cause
def _normalize_common_cause(raw: dict, _payload: dict) -> dict:
    return {
        "probable_common_cause": _text(raw.get("probable_common_cause")),
        "evidence": _str_list(raw.get("evidence", []))[:4],
        "confidence": _clamp01(raw.get("confidence")),
    }


# ---------------------------------------------------------------- summarize_chat
def _prepare_chat(payload: dict) -> dict:
    messages = [m for m in payload.get("messages") or [] if isinstance(m, dict)][-MAX_CHAT_MESSAGES:]
    slim = [
        {
            k: (str(m[k])[:MAX_MESSAGE_CHARS] if k == "text" else m[k])
            for k in ("role", "text", "quick_action", "created_at")
            if m.get(k)
        }
        for m in messages
    ]
    return {"incident_id": payload.get("incident_id"), "messages": slim}


def _normalize_chat(raw: dict, _payload: dict) -> dict:
    root_cause = raw.get("root_cause")
    return {
        "summary": _text(raw.get("summary")),
        "root_cause": root_cause.strip() if isinstance(root_cause, str) and root_cause.strip() else None,
        "actions_taken": _str_list(raw.get("actions_taken", [])),
        "parts_replaced": _str_list(raw.get("parts_replaced", [])),
    }


# ---------------------------------------------------------------- executive_report
def _normalize_report(raw: dict, _payload: dict) -> dict:
    return {"summary_text": _text(raw.get("summary_text"))}


def _identity(payload: dict) -> dict:
    return payload


TASKS: dict[str, TaskSpec] = {
    "diagnose": TaskSpec(
        schema=lambda _p: _obj(
            {"probable_cause": STRING, "suggested_action": STRING, "confidence": NUMBER, "parts_suggested": STRING_LIST}
        ),
        prepare=_prepare_diagnose,
        normalize=_normalize_diagnose,
        fallback=ia_fallbacks.diagnose,
    ),
    "summarize_by_role": TaskSpec(
        schema=_roles_schema, prepare=_identity, normalize=_normalize_by_role, fallback=ia_fallbacks.summarize_by_role
    ),
    "common_cause": TaskSpec(
        schema=lambda _p: _obj({"probable_common_cause": STRING, "evidence": STRING_LIST, "confidence": NUMBER}),
        prepare=_identity,
        normalize=_normalize_common_cause,
        fallback=ia_fallbacks.common_cause,
    ),
    "summarize_chat": TaskSpec(
        schema=lambda _p: _obj(
            {
                "summary": STRING,
                "root_cause": {"type": "STRING", "nullable": True},
                "actions_taken": STRING_LIST,
                "parts_replaced": STRING_LIST,
            }
        ),
        prepare=_prepare_chat,
        normalize=_normalize_chat,
        fallback=ia_fallbacks.summarize_chat,
    ),
    "executive_report": TaskSpec(
        schema=lambda _p: _obj({"summary_text": STRING}),
        prepare=_identity,
        normalize=_normalize_report,
        fallback=ia_fallbacks.executive_report,
    ),
}


def payload_json(payload: dict) -> str:
    """Serializa el payload para insertarlo en el prompt."""
    return json.dumps(payload, ensure_ascii=False, indent=1, default=str)
