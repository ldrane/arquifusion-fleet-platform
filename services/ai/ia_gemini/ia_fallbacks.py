"""Respuestas deterministas cuando el LLM (Gemini o Bedrock) no está disponible.

MH-MC-03: la IA nunca bloquea el flujo.

Cada función recibe el `payload` del contrato (contratos.md §8) y devuelve un `result` con la misma forma
que la respuesta de Gemini. Son defensivas: un payload incompleto produce un texto genérico, nunca una excepción.
"""

import re

# Variable de telemetría -> (causa probable, acción sugerida). Base de conocimiento mínima de mantenimiento.
CAUSES_BY_VARIABLE: dict[str, tuple[str, str]] = {
    "vibration_mm_s": (
        "Desgaste de rodamientos o desbalance en el tren de potencia",
        "Inspeccionar rodamientos, anclajes y lubricación",
    ),
    "temperature_c": (
        "Sobrecalentamiento por falla de refrigeración o lubricación",
        "Revisar nivel de refrigerante, radiador y aceite del motor",
    ),
    "pressure_bar": (
        "Anomalía en el sistema hidráulico (fuga, filtro obstruido o bomba)",
        "Inspeccionar mangueras, filtros y presión de la bomba hidráulica",
    ),
    "fuel_rate_lph": (
        "Consumo de combustible excesivo (inyectores, filtro de aire o sobrecarga)",
        "Revisar inyectores y filtro de aire; validar la carga de trabajo",
    ),
    "rpm": (
        "Régimen de motor anómalo (gobernador o transmisión)",
        "Revisar el gobernador del motor y la transmisión",
    ),
}
COMBINED_CAUSES: dict[frozenset[str], tuple[str, str]] = {
    frozenset({"temperature_c", "vibration_mm_s"}): (
        "Fricción por falla de rodamientos con sobrecalentamiento asociado",
        "Detener la máquina e inspeccionar rodamientos y lubricación antes de continuar",
    ),
    frozenset({"temperature_c", "fuel_rate_lph"}): (
        "Motor trabajando forzado: posible obstrucción de admisión o refrigeración deficiente",
        "Revisar filtro de aire, radiador e inyectores",
    ),
}
COMMON_CAUSE_BY_VARIABLE: dict[str, str] = {
    "fuel_rate_lph": "Combustible contaminado o de un mismo lote defectuoso",
    "temperature_c": "Condiciones climáticas extremas en la zona",
    "vibration_mm_s": "Terreno irregular o deterioro de vías en la zona",
    "pressure_bar": "Lote de componentes hidráulicos defectuoso",
    "rpm": "Condiciones de operación exigentes en la zona (pendientes, sobrecarga)",
}
GENERIC = ("Comportamiento anómalo multivariable sin causa dominante", "Programar una inspección general de la máquina")

# Repuestos probables por variable dominante: palabras clave sobre `candidate_parts[].name` (contratos.md §8.1).
# Solo se devuelven IDs presentes en `candidate_parts`, así la regla de `required_specialty` (§8.2) también
# funciona en modo degradado.
PART_KEYWORDS: dict[str, tuple[str, ...]] = {
    "vibration_mm_s": ("rodamiento",),
    "temperature_c": ("rodamiento", "radiador", "bomba de agua"),
    "pressure_bar": ("manguera hidráulica", "válvula de control hidráulico", "bomba hidráulica"),
    "fuel_rate_lph": ("inyector", "filtro de combustible"),
    "rpm": ("alternador", "módulo de control"),
    "speed_kmh": ("neumático", "zapata"),
}
MAX_FALLBACK_PARTS = 2


def _factor_names(factors) -> list[str]:
    return [f.get("variable") for f in factors or [] if isinstance(f, dict) and f.get("variable")]


def _parts_for(variables: list[str], candidates) -> list[str]:
    parts = [p for p in candidates or [] if isinstance(p, dict) and p.get("component_id") and p.get("name")]
    chosen: list[str] = []
    for variable in variables:
        for keyword in PART_KEYWORDS.get(variable, ()):
            for part in parts:
                if keyword in part["name"].lower() and part["component_id"] not in chosen:
                    chosen.append(part["component_id"])
        if chosen:
            break
    return chosen[:MAX_FALLBACK_PARTS]


def diagnose(payload: dict) -> dict:
    names = _factor_names(payload.get("top_factors"))
    cause, action = GENERIC
    for pair, value in COMBINED_CAUSES.items():
        if pair <= set(names[:2]):
            cause, action = value
            break
    else:
        if names and names[0] in CAUSES_BY_VARIABLE:
            cause, action = CAUSES_BY_VARIABLE[names[0]]
    return {
        "probable_cause": cause,
        "suggested_action": action,
        "confidence": 0.4 if names else 0.2,
        "parts_suggested": _parts_for(names[:2], payload.get("candidate_parts")),
    }


def summarize_by_role(payload: dict) -> dict:
    incident = payload.get("incident") or {}
    machines = ", ".join(incident.get("machine_ids") or []) or "una máquina"
    severity = incident.get("severity", "desconocida")
    diagnosis = (incident.get("ai_diagnosis") or {}).get("probable_cause") or "en análisis"
    technician = incident.get("assigned_technician_id") or "por asignar"
    texts = {
        "operador": f"Severidad {severity}. Reduce la carga de {machines} y espera indicaciones del técnico.",
        "tecnico": f"Diagnóstico: {diagnosis}. Severidad {severity}. Revisa el incidente y acepta la asignación.",
        "mantenimiento": f"Técnico {technician}. Severidad {severity}. Verifica repuestos para {machines}.",
        "supervisor": f"Incidente {severity} en zona {incident.get('zone', '-')}. Técnico: {technician}.",
        "admin": f"{machines} con incidente de severidad {severity}. Atención en curso.",
        "gerencia": f"{machines} con incidente de severidad {severity}. Puede afectar la producción de la zona.",
    }
    title = f"{machines} requiere atención"[:60]
    return {
        role: {"title": title, "body": texts.get(role, texts["admin"])[:280]} for role in payload.get("roles") or []
    }


def common_cause(payload: dict) -> dict:
    counts: dict[str, int] = {}
    incidents = payload.get("incidents") or []
    for incident in incidents:
        for name in _factor_names(incident.get("top_factors")):
            counts[name] = counts.get(name, 0) + 1
    if not counts:
        return {
            "probable_common_cause": "Causa común no determinada con los datos disponibles",
            "evidence": [],
            "confidence": 0.1,
        }
    dominant = max(counts, key=counts.get)
    evidence = [f"{counts[dominant]} de {len(incidents)} máquinas con desviación en {dominant}"]
    if payload.get("zone"):
        evidence.append(f"Todas en la zona {payload['zone']} dentro de la misma ventana de tiempo")
    cause = COMMON_CAUSE_BY_VARIABLE.get(dominant, "Condición de operación compartida en la zona")
    return {"probable_common_cause": cause, "evidence": evidence, "confidence": 0.35}


# ---------------------------------------------------------------- summarize_chat (RF-16.8)
# Mensajes que no son conversación del chat (p. ej. notas de resolución o eventos del sistema, si un llamador
# los marca con `kind`/`type`/`source`) se descartan: el resumen de cierre es solo del chat.
NON_CHAT_KINDS = {"resolution", "resolution_notes", "system", "event"}
MIN_WORD = 5


def chat_messages(payload: dict) -> list[dict]:
    """Mensajes del chat del incidente con texto o acción rápida, sin entradas que no sean conversación."""
    out = []
    for m in payload.get("messages") or []:
        if not isinstance(m, dict) or not (m.get("text") or m.get("quick_action")):
            continue
        if any(str(m.get(k, "")).lower() in NON_CHAT_KINDS for k in ("kind", "type", "source")):
            continue
        out.append(m)
    return out


def chat_text(payload: dict) -> str:
    return "\n".join(str(m.get("text") or "") for m in chat_messages(payload)).lower()


def mentioned(item: str, text: str) -> bool:
    """True si `item` (o alguna de sus palabras significativas) aparece en el texto del chat."""
    item = item.lower().strip()
    if not item:
        return False
    if item in text:
        return True
    words = [w for w in re.findall(r"[\wáéíóúñ-]+", item) if len(w) >= MIN_WORD]
    return any(w in text for w in words)


def summarize_chat(payload: dict) -> dict:
    messages = chat_messages(payload)
    texts = [str(m["text"]).strip() for m in messages if str(m.get("text") or "").strip()]
    if not messages:
        summary = "No hubo conversación en el chat del incidente."
    else:
        roles = sorted({str(m["role"]) for m in messages if m.get("role")})
        who = f" entre {', '.join(roles)}" if roles else ""
        summary = f"Conversación de {len(messages)} mensajes{who}."
        if texts:
            summary += f" Inicio: «{texts[0][:120]}»."
        if len(texts) > 1:
            summary += f" Cierre: «{texts[-1][:120]}»."
    actions = list(dict.fromkeys(str(m["quick_action"]) for m in messages if m.get("quick_action")))
    # Sin LLM no se puede distinguir "reemplacé X" de "¿hay stock de X?": no se afirma ningún repuesto.
    return {"summary": summary, "root_cause": None, "actions_taken": actions, "parts_replaced": []}


def executive_report(payload: dict) -> dict:
    figures = payload.get("figures") or {}
    kpis = figures.get("kpis_7d") or figures
    parts = []
    labels = (
        ("availability_pct", "Disponibilidad de flota {:.1f}%"),
        ("mttr_hours", "MTTR {:.1f} h"),
        ("open_incidents", "{} incidentes abiertos"),
        ("machines_at_risk", "{} máquinas en riesgo"),
        ("fuel_cost_per_ton_usd", "combustible {:.2f} USD/t"),
    )
    for key, label in labels:
        if isinstance(kpis.get(key), (int, float)):
            parts.append(label.format(kpis[key]))
    text = "Resumen de los últimos 7 días: " + (", ".join(parts) if parts else "sin cifras disponibles") + "."
    if isinstance(kpis.get("machines_at_risk"), int) and kpis["machines_at_risk"] > 0:
        text += " Prioridad: atender las máquinas en riesgo antes del próximo turno."
    return {"summary_text": text}
