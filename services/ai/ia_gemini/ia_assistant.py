"""Asistente conversacional con function calling (RF-14).

`answer_with_llm` deja que el proveedor LLM configurado (Gemini o Bedrock, ver llm_client) decida qué funciones
de lectura invocar. Si el LLM falla o se agota el presupuesto de tiempo, `answer_deterministic` enruta la pregunta
por palabras clave a las mismas funciones (respuesta `degraded`).
"""

import json
import re
import time

from ia_tools import FUNCTION_DECLARATIONS, ToolBox
from llm_client import LLMClient, LLMError

MAX_TOOL_ROUNDS = 4
# API Gateway corta a los 29 s y la Lambda a los 30 s. El deadline global deja margen para el arranque en frío,
# la lectura del secreto y la respuesta determinista (scan en DynamoDB) si el LLM no termina a tiempo.
TOTAL_BUDGET_S = 20.0
MIN_ROUND_S = 2.0  # no se abre una ronda nueva con menos tiempo que esto
MACHINE_ID = re.compile(r"\b([A-Za-z]{2}-\d{3,4})\b")
ZONE = re.compile(r"\bzona\s+([a-záéíóúñ]+)", re.IGNORECASE)


def answer_with_llm(
    message: str, llm: LLMClient, tools: ToolBox, system: str, budget_s: float = TOTAL_BUDGET_S
) -> tuple[str, list[str]]:
    """Ciclo de function calling con deadline global. Devuelve (respuesta, funciones usadas) o lanza LLMError."""
    deadline = time.monotonic() + budget_s
    history: list[dict] = [{"role": "user", "text": message}]
    used: list[str] = []
    for _ in range(MAX_TOOL_ROUNDS):
        remaining = deadline - time.monotonic()
        if remaining < MIN_ROUND_S:
            break
        turn = llm.chat(history=history, system=system, tools=FUNCTION_DECLARATIONS, timeout_s=remaining)
        if not turn.tool_calls:
            if not turn.text:
                raise LLMError("respuesta vacía del asistente")
            return turn.text, used
        history.append({"role": "assistant", "turn": turn})
        results = []
        for call in turn.tool_calls:
            used.append(call.name)
            results.append((call, tools.call(call.name, call.args or {})))
        history.append({"role": "tool", "results": results})
    raise LLMError("el asistente no terminó dentro del presupuesto de tiempo o rondas")


def answer_deterministic(message: str, tools: ToolBox) -> tuple[str, list[str]]:
    """Respuesta sin LLM: elige una función por palabras clave y formatea su resultado."""
    text = message.lower()
    zone_match = ZONE.search(message)
    zone = zone_match.group(1).lower() if zone_match else None
    machine_match = MACHINE_ID.search(message)

    if machine_match:
        name, data = "get_machine_detail", tools.get_machine_detail(machine_match.group(1).upper())
        return _format_machine(data), [name]
    if "incidente" in text:
        data = tools.get_open_incidents(zone)
        lines = [f"- {i['incident_id']} ({i.get('severity')}, {i.get('status')})" for i in data["incidents"]]
        return _with_list(f"Hay {data['total']} incidentes abiertos", zone, lines), ["get_open_incidents"]
    if "combustible" in text:
        return _format_insight(tools.get_insight("fuel#7d"), "Combustible (7 días)"), ["get_insight"]
    if "mantenimiento" in text:
        return _format_insight(tools.get_insight("maintenance_plan"), "Plan de mantenimiento"), ["get_insight"]
    if "repuesto" in text:
        return _format_insight(tools.get_insight("parts_forecast#30"), "Pronóstico de repuestos (30 días)"), [
            "get_insight"
        ]
    if any(word in text for word in ("riesgo", "crític", "critic", "peligro", "falla")):
        data = tools.get_machines_at_risk(zone)
        lines = [f"- {m['machine_id']}: health {m.get('health_score')}, {m.get('status')}" for m in data["machines"]]
        return _with_list(f"Hay {data['total']} máquinas en riesgo", zone, lines), ["get_machines_at_risk"]
    return (
        "El asistente funciona en modo básico. Puedo informarte sobre máquinas en riesgo, una máquina por su ID "
        "(por ejemplo EX-023), incidentes abiertos, mantenimiento, repuestos o combustible.",
        [],
    )


def _with_list(head: str, zone: str | None, lines: list[str]) -> str:
    head += f" en la zona {zone}" if zone else ""
    return head + (":\n" + "\n".join(lines) if lines else ".")


def _format_machine(data: dict) -> str:
    if "error" in data:
        return data["error"]
    return (
        f"{data['machine_id']} ({data.get('type', '-')}, zona {data.get('zone', '-')}): "
        f"estado {data.get('status', '-')}, "
        f"health {data.get('health_score', '-')}, próximo mantenimiento {data.get('next_maintenance_at', '-')}."
    )


def _format_insight(data: dict, title: str) -> str:
    if "error" in data:
        return data["error"]
    rows = data["data"] if isinstance(data["data"], list) else [data["data"]]
    preview = "\n".join(f"- {json.dumps(row, ensure_ascii=False)}" for row in rows[:5])
    return f"{title}, generado el {data.get('generated_at', '-')}:\n{preview}"
