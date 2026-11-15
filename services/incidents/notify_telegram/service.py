"""notify_telegram (RF-10.1, RF-10.2): alertas CRÍTICAS a Telegram. Contrato del evento: contratos.md §3 y §10.

Suscripción propia en EventBridge (regla `{p}-telegram`, infra/incidents): `IncidentStateChanged` con
`detail.data.severity = critical` y `event_type` dentro de `var.telegram_event_types`. No pasa por
notification-rules: es un canal de guardia para los incidentes críticos, independiente del push/email por rol.

Pasos: normaliza el envoltorio de EventBridge → re-filtra (defensa si la regla cambia) → lee el secreto
`{bot_token, chat_ids}` (sin secreto = se omite sin error) → por cada chat: reserva `TG#<event_id>#<chat>` en
`idempotency` (EventBridge reintenta: no se duplica) → `sendMessage`. Si un envío falla se libera la reserva y,
si fallaron todos, se relanza para que EventBridge reintente.
"""
import html
import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
DEFAULT_EVENT_TYPES = ("incident.detected", "incident.assigned", "incident.escalated", "incident.resolved")

HEADERS = {
    "incident.detected": "🚨 CRÍTICO · {machine_id} requiere intervención",
    "incident.assigned": "🛠️ CRÍTICO · {machine_id}: técnico asignado",
    "incident.in_progress": "🔧 CRÍTICO · {machine_id}: técnico en atención",
    "incident.escalated": "⏫ CRÍTICO · {machine_id}: incidente escalado",
    "incident.resolved": "✅ {machine_id}: incidente crítico resuelto",
    "incident.closed": "📁 {machine_id}: incidente crítico cerrado",
}
LABELS = {
    "incident.detected": "anomalía detectada",
    "incident.assigned": "técnico asignado",
    "incident.in_progress": "en atención",
    "incident.escalated": "escalado: nadie aceptó a tiempo",
    "incident.resolved": "resuelto",
    "incident.closed": "cerrado",
}


def normalize(event: dict) -> dict:
    """`detail.data` + `correlation_id`/`event_id` del envoltorio de EventBridge (o la invocación directa)."""
    if isinstance(event.get("detail"), dict):
        detail = event["detail"]
        data = dict(detail.get("data") or {})
        data.setdefault("correlation_id", detail.get("correlation_id"))
        data.setdefault("event_id", detail.get("event_id") or event.get("id"))
        return data
    return dict(event)


def parse_config(raw: str | None) -> dict | None:
    """Secreto JSON `{bot_token, chat_ids, webhook_secret?, links?}`; `chat_ids` acepta lista o string
    separado por comas. También acepta `chat_id` (singular). Las claves del webhook son opcionales y se
    conservan para que `api_comandos` valide el secret token y resuelva el actor por chat."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    chats = data.get("chat_ids", data.get("chat_id"))
    if isinstance(chats, str | int):
        chats = str(chats).split(",")
    chats = [str(c).strip() for c in chats or [] if str(c).strip()]
    token = str(data.get("bot_token") or "").strip()
    if not token or not chats:
        return None
    config = {"bot_token": token, "chat_ids": chats}
    secret = str(data.get("webhook_secret") or "").strip()
    if secret:
        config["webhook_secret"] = secret
    if isinstance(data.get("links"), dict):
        config["links"] = data["links"]
    return config


def _score(incident: dict | None, technician_id: str | None) -> float | None:
    """Score del técnico asignado: `technician_score` o su entrada en `scoring_candidates`."""
    if not incident:
        return None
    score = incident.get("technician_score")
    if score is not None:
        return score
    for candidate in incident.get("scoring_candidates") or []:
        if isinstance(candidate, dict) and candidate.get("technician_id") == technician_id:
            return candidate.get("score")
    return None


def compose(msg: dict, incident: dict | None, app_url: str = "", buttons: bool = True) -> tuple[str, dict | None]:
    """Texto HTML de Telegram + teclado inline.

    `incident.assigned` agrega los botones Aceptar/Rechazar (si `callback_data` cabe en 64 bytes) antes del
    deep link. El botón "Abrir incidente" solo se agrega con `app_url` https.
    """
    e = html.escape
    machine = msg.get("machine_id") or "-"
    event_type = msg.get("event_type") or ""
    header = HEADERS.get(event_type, "🚨 CRÍTICO · {machine_id}: " + event_type).format(machine_id=machine)
    lines = [f"<b>{e(header)}</b>", ""]
    lines.append(f"📍 Zona: <b>{e(str(msg.get('zone') or '-'))}</b>")
    if msg.get("incident_id"):
        lines.append(f"🆔 Incidente: <code>{e(msg['incident_id'])}</code>")
    lines.append(f"📌 Estado: {e(LABELS.get(event_type, msg.get('to') or event_type))}")
    tech = msg.get("technician_id") or (incident or {}).get("assigned_technician_id")
    if tech:
        lines.append(f"👷 Técnico: {e(str(tech))}")
        score = _score(incident, tech)
        if score is not None:
            try:
                lines.append(f"🧾 Técnico sugerido: {e(str(tech))} (score {float(score):.2f})")
            except (TypeError, ValueError):
                lines.append(f"🧾 Técnico sugerido: {e(str(tech))}")
    diag = (incident or {}).get("ai_diagnosis") or {}
    factors = diag.get("top_factors") or []
    if factors:
        f0 = factors[0]
        try:
            z = f"{float(f0.get('z_score', 0)):.1f}σ"
        except (TypeError, ValueError):
            z = "?σ"
        lines.append(f"📈 {e(str(f0.get('variable')))} {z} sobre su baseline")
    if diag.get("probable_cause"):
        lines.append(f"🧠 Causa probable: {e(str(diag['probable_cause']))}")
    if diag.get("suggested_action"):
        lines.append(f"🧰 Acción sugerida: {e(str(diag['suggested_action']))}")
    text = "\n".join(lines)[:4000]  # límite de Telegram: 4096

    rows = []
    incident_id = msg.get("incident_id")
    if buttons and event_type == "incident.assigned" and incident_id:
        callbacks = [f"ack:{incident_id}:accept", f"ack:{incident_id}:reject"]
        if all(len(cb.encode()) <= 64 for cb in callbacks):
            rows.append([
                {"text": "✅ Aceptar", "callback_data": callbacks[0]},
                {"text": "❌ Rechazar", "callback_data": callbacks[1]},
            ])
    if app_url.startswith("https://") and incident_id:
        link = f"{app_url.rstrip('/')}/incidents/{incident_id}"
        rows.append([{"text": "Abrir incidente", "url": link}])
    return text, ({"inline_keyboard": rows} if rows else None)


class TelegramNotifier:
    """`deps`: config() → dict|None, claim(key) → bool, release(key), incident(id) → dict|None,
    send(token, chat_id, text, markup)."""

    def __init__(self, deps: dict, event_types=DEFAULT_EVENT_TYPES, app_url: str = "",
                 min_severity: str = "critical"):
        self.d = deps
        self.event_types = set(event_types)
        self.app_url = app_url
        self.severities = {"high", "critical"} if min_severity == "high" else {"critical"}

    def run(self, event: dict) -> dict:
        msg = normalize(event)
        result = {"event_type": msg.get("event_type"), "incident_id": msg.get("incident_id"), "sent": 0}
        if msg.get("severity") not in self.severities:
            return {**result, "skipped": "severity"}
        if msg.get("event_type") not in self.event_types:
            return {**result, "skipped": "event_type"}
        cfg = self.d["config"]()
        if not cfg:
            log.warning("Telegram sin configurar (secreto vacío): se omite %s", msg.get("incident_id"))
            return {**result, "skipped": "sin configuración"}

        incident = None
        if msg.get("incident_id"):
            try:
                incident = self.d["incident"](msg["incident_id"])
            except Exception:  # noqa: BLE001 - el diagnóstico es opcional, la alerta sale igual
                log.exception("No se pudo leer el incidente %s", msg["incident_id"])
        text, markup = compose(msg, incident, self.app_url)

        dedup_base = msg.get("event_id") or f"{msg.get('incident_id')}#{msg.get('event_type')}"
        failed, duplicates = [], 0
        for chat in cfg["chat_ids"]:
            key = f"TG#{dedup_base}#{chat}"
            if not self.d["claim"](key):
                duplicates += 1
                continue
            try:
                self.d["send"](cfg["bot_token"], chat, text, markup)
                result["sent"] += 1
            except Exception:  # noqa: BLE001 - un chat caído no tumba a los demás
                log.exception("Falló el envío a Telegram (chat %s, %s)", chat, msg.get("correlation_id"))
                self.d["release"](key)
                failed.append(chat)
        if duplicates:
            result["duplicates"] = duplicates
        if failed:
            result["failed"] = len(failed)
            if not result["sent"] and not duplicates:
                raise RuntimeError(f"Telegram falló para todos los chats ({len(failed)})")
        return result


def send_message(token: str, chat_id: str, text: str, markup: dict | None = None,
                 timeout: float = 8.0) -> dict:  # pragma: no cover - red
    body = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if markup:
        body["reply_markup"] = markup
    req = urllib.request.Request(
        API_URL.format(token=token), data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - URL fija de Telegram
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:  # no se loguea la URL: lleva el token
        detail = exc.read().decode(errors="replace")[:300]
        raise RuntimeError(f"Telegram HTTP {exc.code}: {detail}") from None
