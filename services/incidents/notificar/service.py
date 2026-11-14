"""notificar (RF-10.1, RF-10.2, RF-10.3, RF-10.5). Contrato: contratos.md §4 y §10.

Entrada (dos formas):
- Invocación directa desde la SFN:
  `{event_type, incident_id?, machine_id, zone, severity, technician_id?, correlation_id}`
  (la usa la SFN para `parts.shortage`; sirve también para `report.daily`).
- Evento EventBridge `IncidentStateChanged` (regla en infra/incidents): se usa `detail.data` + `detail.correlation_id`.

Pasos: `Query notification-rules pk = EVENT#<event_type>` → filtra `enabled` y `severity ≥ severity_min` →
throttle (PutItem condicional `NTF#…` en idempotency) → redacta según `content_profile` → envía por canal:
`push` → Pub/Sub `notificaciones` (→ notify_bridge → FCM), `email` → SNS `{p}-alerts-{rol}`, `dashboard` → nada.
"""
import json
import logging
import os
import time
import uuid

log = logging.getLogger(__name__)

SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}

TITLES = {
    "incident.detected": "{machine_id} requiere intervención",
    "machine.silent": "{machine_id} dejó de reportar",
    "incident.assigned": "{machine_id}: incidente asignado",
    "incident.in_progress": "{machine_id}: técnico en atención",
    "incident.resolved": "{machine_id}: incidente resuelto",
    "incident.closed": "{machine_id}: incidente cerrado",
    "incident.escalated": "{machine_id}: incidente escalado",
    "parts.shortage": "Falta de repuesto en zona {zone}",
    "report.daily": "Reporte diario disponible",
}
LABELS = {
    "incident.detected": "anomalía detectada",
    "machine.silent": "sin telemetría",
    "incident.assigned": "técnico asignado",
    "incident.in_progress": "en atención",
    "incident.resolved": "resuelto",
    "incident.closed": "cerrado",
    "incident.escalated": "escalado: nadie aceptó a tiempo",
    "parts.shortage": "sin stock del repuesto sugerido",
    "report.daily": "reporte ejecutivo generado",
}


def normalize(event: dict) -> dict:
    """Acepta la invocación directa o el envoltorio de EventBridge."""
    if "detail" in event and isinstance(event["detail"], dict):
        detail = event["detail"]
        data = dict(detail.get("data") or {})
        data.setdefault("correlation_id", detail.get("correlation_id"))
        return data
    return dict(event)


def applicable(rules: list[dict], severity: str | None) -> list[dict]:
    level = SEVERITY_ORDER.get(severity or "info", 0)
    return [
        r
        for r in rules
        if r.get("enabled", True) and level >= SEVERITY_ORDER.get(r.get("severity_min") or "info", 0)
    ]


def throttle_key(msg: dict, role: str, technician_id: str | None) -> str:
    """`NTF#<event_type>#<role>#<incident_id|machine_id>` (§10). Para el técnico destinatario se agrega su id,
    así una reasignación al siguiente candidato no queda silenciada por el throttle del anterior."""
    key = f"NTF#{msg['event_type']}#{role}#{msg.get('incident_id') or msg.get('machine_id') or msg.get('zone')}"
    return f"{key}#{technician_id}" if technician_id else key


def compose(msg: dict, profile: str, incident: dict | None) -> tuple[str, str]:
    fmt = {"machine_id": msg.get("machine_id") or "-", "zone": msg.get("zone") or "-"}
    title = TITLES.get(msg["event_type"], msg["event_type"]).format(**fmt)
    label = LABELS.get(msg["event_type"], msg["event_type"])
    sev = msg.get("severity") or "info"
    diag = (incident or {}).get("ai_diagnosis") or {}
    if profile == "technical":
        parts = [f"{fmt['machine_id']} ({fmt['zone']}), severidad {sev}: {label}."]
        factors = diag.get("top_factors") or []
        if factors:
            f0 = factors[0]
            parts.append(f"{f0.get('variable')} {float(f0.get('z_score', 0)):.1f}σ sobre su baseline.")
        if diag.get("probable_cause"):
            parts.append(f"Causa probable: {diag['probable_cause']}.")
        if diag.get("suggested_action"):
            parts.append(f"Acción sugerida: {diag['suggested_action']}.")
        body = " ".join(parts)
    elif profile == "executive":
        body = f"Incidente {sev} en {fmt['machine_id']} (zona {fmt['zone']}): {label}."
        if incident and incident.get("downtime_minutes") is not None:
            body += f" Tiempo detenido: {incident['downtime_minutes']} min."
    else:  # operational
        body = f"{fmt['machine_id']} en zona {fmt['zone']}: {label}. Severidad {sev}."
    return title, body[:500]


class Notifier:
    def __init__(self, deps: dict):
        self.d = deps

    def run(self, event: dict) -> dict:
        msg = normalize(event)
        if not msg.get("event_type"):
            raise ValueError("Falta event_type")
        rules = applicable(self.d["rules"](msg["event_type"]), msg.get("severity"))
        result = {"event_type": msg["event_type"], "incident_id": msg.get("incident_id"), "sent": [], "throttled": []}
        if not rules:
            return result
        incident = self.d["incident"](msg["incident_id"]) if msg.get("incident_id") else None
        for rule in rules:
            role = rule["role"]
            channels = [c for c in rule.get("channels") or [] if c != "dashboard"]
            if not channels:
                continue
            target_user, target_tech = None, None
            if role == "tecnico" and msg["event_type"].startswith("incident."):
                target_tech = msg.get("technician_id") or (incident or {}).get("assigned_technician_id")
                if not target_tech:
                    continue  # §10: el técnico solo recibe lo suyo
                target_user = (self.d["technician"](target_tech) or {}).get("user_id")
            minutes = int(rule.get("throttle_minutes") or 0)  # 0 = sin throttle
            if minutes > 0 and not self.d["throttle"](throttle_key(msg, role, target_tech), minutes):
                result["throttled"].append(role)
                continue
            title, body = compose(msg, rule.get("content_profile") or "operational", incident)
            for channel in channels:
                try:
                    if channel == "push":
                        self._push(msg, role, target_user, title, body)
                    elif channel == "email":
                        self._email(msg, role, title, body)
                    else:
                        continue
                    result["sent"].append({"role": role, "channel": channel, "user_id": target_user})
                except Exception:  # noqa: BLE001 - un canal caído no tumba a los demás
                    log.exception("Falló el canal %s para %s (%s)", channel, role, msg.get("correlation_id"))
        return result

    def _push(self, msg, role, user_id, title, body):
        incident_id = msg.get("incident_id")
        payload = {
            "notification_id": f"ntf-{uuid.uuid4().hex[:12]}",
            "correlation_id": msg.get("correlation_id"),
            "event_type": msg["event_type"],
            "incident_id": incident_id,
            "machine_id": msg.get("machine_id"),
            "zone": msg.get("zone"),
            "target": {"role": role, "zone": msg.get("zone"), "user_id": user_id},
            "severity": msg.get("severity"),
            "title": title,
            "body": body,
            "deep_link": f"/incidents/{incident_id}" if incident_id else "/",
        }
        attrs = {
            "correlation_id": msg.get("correlation_id"),
            "incident_id": incident_id,
            "event_type": msg["event_type"],
        }
        self.d["pubsub"](payload, attrs)

    def _email(self, msg, role, title, body):
        self.d["sns"](role, title, body, {"zone": msg.get("zone"), "severity": msg.get("severity")})


# ---------- dependencias reales ----------

def _default_deps() -> dict:  # pragma: no cover - requiere AWS
    import boto3
    from arquifusion_shared import config
    from boto3.dynamodb.conditions import Key
    from gcp_auth import PubSubPublisher

    ddb = boto3.resource("dynamodb")
    rules_t = ddb.Table(config.table("notification-rules"))
    idem_t = ddb.Table(config.table("idempotency"))
    inc_t = ddb.Table(config.table("incidents"))
    tech_t = ddb.Table(config.table("technicians"))
    sns = boto3.client("sns")
    topic_prefix = os.environ["ALERTS_TOPIC_ARN_PREFIX"]  # arn:aws:sns:<region>:<acct>:arquifusion-<stage>-alerts-

    def rules(event_type):
        return rules_t.query(KeyConditionExpression=Key("pk").eq(f"EVENT#{event_type}")).get("Items", [])

    def throttle(key, minutes):
        now = int(time.time())
        try:
            idem_t.put_item(
                Item={"pk": key, "expires_at": now + minutes * 60, "created_at": now},
                ConditionExpression="attribute_not_exists(pk) OR expires_at < :now",
                ExpressionAttributeValues={":now": now},
            )
            return True
        except idem_t.meta.client.exceptions.ConditionalCheckFailedException:
            return False

    def sns_publish(role, subject, body, attrs):
        sns.publish(
            TopicArn=f"{topic_prefix}{role}",
            Subject=subject[:100],
            Message=body,
            MessageAttributes={k: {"DataType": "String", "StringValue": str(v)} for k, v in attrs.items() if v},
        )

    publisher = None

    def pubsub(payload, attrs):
        nonlocal publisher
        if publisher is None:
            from aws_lambda_powertools.utilities import parameters

            secret = os.environ["GCP_SA_SECRET_NAME"]
            publisher = PubSubPublisher(
                lambda: json.loads(parameters.get_secret(secret, max_age=300)),
                os.environ.get("PUBSUB_TOPIC", "notificaciones"),
            )
        publisher.publish(payload, attrs)

    return {
        "rules": rules,
        "throttle": throttle,
        "incident": lambda iid: inc_t.get_item(Key={"pk": f"INC#{iid}", "sk": "META"}).get("Item"),
        "technician": lambda tid: tech_t.get_item(Key={"pk": f"TECH#{tid}", "sk": "META"}).get("Item"),
        "sns": sns_publish,
        "pubsub": pubsub,
    }


_DEPS: dict | None = None


def run(event: dict, deps: dict | None = None) -> dict:
    global _DEPS
    if deps is None:
        _DEPS = _DEPS or _default_deps()
        deps = _DEPS
    return Notifier(deps).run(event)
