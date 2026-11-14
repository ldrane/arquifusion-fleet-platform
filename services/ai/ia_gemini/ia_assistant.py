"""Asistente conversacional con function calling (RF-14).

`answer_with_gemini` deja que Gemini decida qué funciones de lectura invocar. Si Gemini falla,
`answer_deterministic` enruta la pregunta por palabras clave a las mismas funciones (respuesta `degraded`).
"""

import json
import re
import time

from gemini_client import GeminiClient, GeminiError
from ia_tools import FUNCTION_DECLARATIONS, ToolBox

MAX_TOOL_ROUNDS = 4
TOTAL_BUDGET_S = 20.0  # API Gateway corta a los 29 s; la Lambda tiene 30 s
MACHINE_ID = re.compile(r"\b([A-Za-z]{2}-\d{3,4})\b")
ZONE = re.compile(r"\bzona\s+([a-záéíóúñ]+)", re.IGNORECASE)


def answer_with_gemini(message: str, gemini: GeminiClient, tools: ToolBox, system: str) -> tuple[str, list[str]]:
    """Ciclo de function calling. Devuelve (respuesta, funciones usadas) o lanza GeminiError."""
    deadline = time.monotonic() + TOTAL_BUDGET_S
    contents: list[dict] = [{"role": "user", "parts": [{"text": message}]}]
    used: list[str] = []
    for _ in range(MAX_TOOL_ROUNDS):
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            break
        content = gemini.generate(contents=contents, system=system, tools=FUNCTION_DECLARATIONS, timeout_s=remaining)
        calls = [part["functionCall"] for part in content["parts"] if "functionCall" in part]
        if not calls:
            text = "".join(part.get("text", "") for part in content["parts"]).strip()
            if not text:
                raise GeminiError("respuesta vacía del asistente")
            return text, used
        contents.append({"role": "model", "parts": content["parts"]})
        responses = []
        for call in calls:
            used.append(call["name"])
            result = tools.call(call["name"], call.get("args") or {})
            responses.append({"functionResponse": {"name": call["name"], "response": {"result": result}}})
        contents.append({"role": "user", "parts": responses})
    raise GeminiError("el asistente no terminó dentro del presupuesto de tiempo o rondas")


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
