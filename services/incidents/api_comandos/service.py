"""Lógica de negocio de api_comandos (RF-06.1, RF-06.4, RF-11.1, RF-13.2, RF-16.5, TRZ-02).

Comandos: ack, assign, resolve, technicians/me/status, ml/retrain y bridge/events (puente GCP → AWS).

Cada comando de incidente valida rol y zona, verifica que el técnico actúe solo sobre lo suyo (#17), lee el
incidente de DynamoDB y avisa a Step Functions con SendTaskSuccess usando el token del ítem META. El output
lleva `actor {type, user_id, role, technician_id}` (TRZ-02). La respuesta es el recurso COMPLETO leído tras el
comando + `meta.pending_transition` (#24). Rutas sin prefijo `/v1` (el stage de API Gateway ya es `v1`).
Los clientes AWS se inyectan (deps) para poder probar sin AWS.
"""
import json
import logging
import math
import os
import re
import time
from decimal import Decimal

from arquifusion_shared import config, correlation, rbac, response
from arquifusion_shared.errors import (
    ApiError,
    Forbidden,
    IncidentStateInvalid,
    NotFound,
    Unauthenticated,
    UpstreamUnavailable,
    ValidationError,
)

log = logging.getLogger(__name__)

# Si Step Functions responde con alguno de estos códigos, el token ya se usó o venció.
_TOKEN_MUERTO = {"InvalidToken", "TaskDoesNotExist", "TaskTimedOut"}
# Nunca salen por la API (dynamodb.md, regla 2)
_SECRET_FIELDS = {"pk", "sk", "entity", "ack_token", "resolve_token", "execution_arn", "seed_version"}
BRIDGE_TTL_S = 7 * 24 * 3600
# Límites de entrada (F-20/F-37): evitan 502 por superar los 256 KB de SendTaskSuccess y claves absurdas.
MAX_REASON = 500
MAX_COMPONENTS = 50
MAX_COMPONENT_LEN = 64
MAX_EVENT_ID = 128
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9._:\-]+$")


# ---------- utilidades ----------

def _default_deps() -> dict:
    import boto3

    ddb = boto3.resource("dynamodb")
    return {
        "incidents": ddb.Table(config.table("incidents")),
        "technicians": ddb.Table(config.table("technicians")),
        "idempotency": ddb.Table(config.table("idempotency")),
        "sfn": boto3.client("stepfunctions"),
        "retrain_arn": os.environ.get("RETRAIN_STATE_MACHINE_ARN"),
    }


_DEPS: dict | None = None


def _deps() -> dict:
    """Clientes AWS una vez por contenedor."""
    global _DEPS
    _DEPS = _DEPS or _default_deps()
    return _DEPS


def _code(exc: Exception) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "")


def _body(event: dict) -> dict:
    raw = event.get("body")
    if isinstance(raw, dict):  # bridge: ya viene como objeto
        return raw
    try:
        body = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ValidationError("El cuerpo no es JSON válido") from exc
    if not isinstance(body, dict):
        raise ValidationError("El cuerpo debe ser un objeto JSON")
    return body


def _path(event: dict, name: str) -> str:
    value = (event.get("pathParameters") or {}).get(name)
    if not value:
        raise ValidationError(f"Falta {name} en la ruta")
    return value


def _public(item: dict) -> dict:
    out = {k: v for k, v in item.items() if k not in _SECRET_FIELDS}
    # F-22: el OpenAPI expone `machine_ids[]` (principal primero), igual que api_lectura
    if "incident_id" in out and not out.get("machine_ids") and out.get("machine_id"):
        out["machine_ids"] = [out["machine_id"]]
    return out


def _get_incident(deps: dict, incident_id: str) -> dict:
    item = deps["incidents"].get_item(Key={"pk": f"INC#{incident_id}", "sk": "META"}).get("Item")
    if not item:
        raise NotFound(f"Incidente {incident_id} no existe")
    return item


def _reread(deps: dict, incident_id: str, fallback: dict) -> dict:
    item = deps["incidents"].get_item(Key={"pk": f"INC#{incident_id}", "sk": "META"}).get("Item") or fallback
    return _public(item)


def _require_status(item: dict, allowed: set[str]) -> None:
    if item.get("status") not in allowed:
        raise IncidentStateInvalid(f"El incidente está en estado '{item.get('status')}'")


def _token(item: dict, name: str) -> str:
    token = item.get(name)
    if not token:
        raise IncidentStateInvalid("El incidente no está esperando esta acción")
    return token


def _actor(event: dict) -> dict:
    return {**rbac.actor(event), "technician_id": rbac.technician_id(event)}


def _require_owner(event: dict, deps: dict, item: dict) -> None:
    """Un `tecnico` solo actúa sobre incidentes asignados a él (#17). Otros roles: validación de zona (#27)."""
    if rbac.role(event) != "tecnico":
        rbac.require_zone(event, item.get("zone"))
        return
    assigned = item.get("assigned_technician_id")
    mine = rbac.technician_id(event)
    if mine:
        if mine != assigned:
            raise Forbidden("El incidente no está asignado a este técnico")
        return
    # Puente GCP sin technician_id: se valida por user_id del técnico asignado
    tech = deps["technicians"].get_item(Key={"pk": f"TECH#{assigned}", "sk": "META"}).get("Item") if assigned else None
    if not tech or tech.get("user_id") != rbac.user_id(event):
        raise Forbidden("El incidente no está asignado a este técnico")


def _send_success(sfn, token: str, output: dict) -> None:
    try:
        sfn.send_task_success(taskToken=token, output=response.dumps(output))
    except Exception as exc:  # noqa: BLE001 - botocore ClientError
        if _code(exc) in _TOKEN_MUERTO:
            raise IncidentStateInvalid("El incidente ya no está esperando esta acción") from exc
        raise UpstreamUnavailable("No se pudo contactar a Step Functions") from exc


def _reason(body: dict):
    """`reason` opcional: texto de hasta 500 caracteres (F-20)."""
    reason = body.get("reason")
    if reason is None:
        return None
    if not isinstance(reason, str) or len(reason) > MAX_REASON:
        raise ValidationError(f"reason debe ser texto de hasta {MAX_REASON} caracteres", [{"field": "reason"}])
    return reason


def _number(value, field: str, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise ValidationError(f"{field} debe ser un número entre {lo} y {hi}", [{"field": field}])
    return value


# ---------- comandos ----------

def ack(event: dict, deps: dict, cid: str):
    rbac.require(event, "tecnico", "mantenimiento")
    incident_id = _path(event, "incident_id")
    body = _body(event)
    decision = body.get("decision")
    if decision not in ("accept", "reject"):
        raise ValidationError("decision debe ser accept o reject", [{"field": "decision"}])
    reason = _reason(body)

    item = _get_incident(deps, incident_id)
    _require_owner(event, deps, item)
    _require_status(item, {"assigned"})
    _send_success(
        deps["sfn"],
        _token(item, "ack_token"),
        {
            "decision": decision,
            "reason": reason,
            "technician_id": item.get("assigned_technician_id"),
            "actor": _actor(event),
            "correlation_id": cid,
        },
    )
    pending = "in_progress" if decision == "accept" else "assigned"
    return _reread(deps, incident_id, item), {"pending_transition": pending}


def assign(event: dict, deps: dict, cid: str):
    rbac.require(event, "mantenimiento", "supervisor", "admin")
    incident_id = _path(event, "incident_id")
    body = _body(event)
    technician_id = body.get("technician_id")
    if not isinstance(technician_id, str) or not technician_id:
        raise ValidationError("technician_id es obligatorio", [{"field": "technician_id"}])
    reason = _reason(body)

    tech = deps["technicians"].get_item(Key={"pk": f"TECH#{technician_id}", "sk": "META"}).get("Item")
    if not tech:
        raise NotFound(f"Técnico {technician_id} no existe")

    item = _get_incident(deps, incident_id)
    rbac.require_zone(event, item.get("zone"))
    # #16: desde `detected` hay token cuando la SFN espera asignación manual (sin candidatos o escalado).
    _require_status(item, {"detected", "assigned"})
    _send_success(
        deps["sfn"],
        _token(item, "ack_token"),
        {
            "decision": "reassign",
            "technician_id": technician_id,
            "reason": reason,
            "actor": _actor(event),
            "correlation_id": cid,
        },
    )
    return _reread(deps, incident_id, item), {"pending_transition": "assigned"}


def resolve(event: dict, deps: dict, cid: str):
    rbac.require(event, "tecnico", "mantenimiento")
    incident_id = _path(event, "incident_id")
    body = _body(event)

    notes = body.get("resolution_notes")
    if not isinstance(notes, str) or not notes.strip():
        raise ValidationError("resolution_notes es obligatorio", [{"field": "resolution_notes"}])
    if len(notes) > 2000:
        raise ValidationError("resolution_notes excede 2000 caracteres", [{"field": "resolution_notes"}])
    components = body.get("components_replaced", [])
    if (
        not isinstance(components, list)
        or len(components) > MAX_COMPONENTS
        or not all(isinstance(c, str) and len(c) <= MAX_COMPONENT_LEN for c in components)
    ):
        raise ValidationError(
            f"components_replaced debe ser lista de hasta {MAX_COMPONENTS} textos", [{"field": "components_replaced"}]
        )
    cost = body.get("cost_usd")
    if cost is not None and (
        isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0
    ):
        raise ValidationError("cost_usd debe ser un número finito >= 0", [{"field": "cost_usd"}])

    item = _get_incident(deps, incident_id)
    _require_owner(event, deps, item)
    _require_status(item, {"in_progress"})
    _send_success(
        deps["sfn"],
        _token(item, "resolve_token"),
        {
            "resolution_notes": notes,
            "components_replaced": components,
            "cost_usd": cost,
            "actor": _actor(event),
            "correlation_id": cid,
        },
    )
    return _reread(deps, incident_id, item), {"pending_transition": "resolved"}


def technician_status(event: dict, deps: dict, cid: str):
    rbac.require(event, "tecnico")
    technician_id = rbac.technician_id(event)
    if not technician_id:
        raise ValidationError("El usuario no tiene custom:technician_id asociado")

    body = _body(event)
    updates = {}
    if "available" in body:
        if not isinstance(body["available"], bool):
            raise ValidationError("available debe ser true o false", [{"field": "available"}])
        updates["available"] = body["available"]
    if "location" in body:
        loc = body["location"]
        if not isinstance(loc, dict):
            raise ValidationError("location debe ser un objeto", [{"field": "location"}])
        updates["location"] = {
            "lat": _number(loc.get("lat"), "location.lat", -90, 90),
            "lon": _number(loc.get("lon"), "location.lon", -180, 180),
        }
    if not updates:
        raise ValidationError("Envía available y/o location")

    current = deps["technicians"].get_item(Key={"pk": f"TECH#{technician_id}", "sk": "META"}).get("Item")
    if not current:
        raise NotFound(f"Técnico {technician_id} no existe")
    if "location" in updates:
        # #11: location.zone = zona del técnico siempre (Firestore filtra por zona)
        updates["location"]["zone"] = current.get("zone")
    updates["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # DynamoDB no acepta float: se convierten a Decimal solo para guardar.
    to_store = json.loads(json.dumps(updates), parse_float=Decimal)
    names = {f"#{k}": k for k in to_store}
    values = {f":{k}": v for k, v in to_store.items()}
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in to_store)
    try:
        attrs = deps["technicians"].update_item(
            Key={"pk": f"TECH#{technician_id}", "sk": "META"},
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(pk)",
            ReturnValues="ALL_NEW",
        ).get("Attributes")
    except Exception as exc:  # noqa: BLE001
        if _code(exc) == "ConditionalCheckFailedException":
            raise NotFound(f"Técnico {technician_id} no existe") from exc
        raise
    return _public(attrs or {**current, **to_store}), {}


def retrain(event: dict, deps: dict, cid: str):
    rbac.require(event, "admin")
    arn = deps.get("retrain_arn")
    if not arn:
        raise UpstreamUnavailable("El workflow de reentrenamiento no está configurado")
    try:
        resp = deps["sfn"].start_execution(
            stateMachineArn=arn,
            input=json.dumps({"correlation_id": cid, "requested_by": rbac.user_id(event), "trigger": "manual"}),
        )
    except Exception as exc:  # noqa: BLE001
        raise UpstreamUnavailable("No se pudo iniciar el reentrenamiento") from exc
    return {"execution_arn": resp["executionArn"]}, {}, 202


# ---------- puente GCP → AWS (RF-16.5, contratos.md §5) ----------

BRIDGE_ROUTES = {
    "incident.ack": ("POST", "/incidents/{incident_id}/ack"),
    "incident.resolve": ("POST", "/incidents/{incident_id}/resolve"),
    "technician.status": ("PUT", "/technicians/me/status"),
}


def bridge_event(event: dict, deps: dict, cid: str):
    """`POST /bridge/events` (API key). Traduce la acción de Firestore al comando `/incidents/*` equivalente,
    con el actor como claims, e idempotencia por `event_id` (`pk = BRG#<event_id>` en idempotency)."""
    body = _body(event)
    event_id = body.get("event_id")
    if event_id is not None and (
        not isinstance(event_id, str) or len(event_id) > MAX_EVENT_ID or not _EVENT_ID_RE.match(event_id)
    ):
        raise ValidationError("event_id inválido (texto simple de hasta 128 caracteres)", [{"field": "event_id"}])
    missing = [f for f in ("event_id", "type", "actor", "occurred_at", "correlation_id") if not body.get(f)]
    if missing:
        raise ValidationError("Faltan campos del BridgeEvent", [{"field": f, "issue": "required"} for f in missing])
    if body["type"] not in BRIDGE_ROUTES:
        raise ValidationError("type no soportado", [{"field": "type"}])
    actor = body["actor"]
    if not isinstance(actor, dict) or actor.get("role") not in rbac.ROLES or not actor.get("user_id"):
        raise ValidationError("actor inválido", [{"field": "actor"}])
    if body["type"].startswith("incident.") and not body.get("incident_id"):
        raise ValidationError("incident_id es obligatorio", [{"field": "incident_id"}])

    data = body.get("data")
    if data is not None and not isinstance(data, dict):  # F-37: una lista daba 500
        raise ValidationError("data debe ser un objeto", [{"field": "data"}])

    key = f"BRG#{body['event_id']}"
    try:
        deps["idempotency"].put_item(
            Item={"pk": key, "expires_at": int(time.time()) + BRIDGE_TTL_S, "type": body["type"]},
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as exc:  # noqa: BLE001
        if _code(exc) == "ConditionalCheckFailedException":
            return {"processed": True, "duplicate": True}, {}
        raise

    claims = {"cognito:username": actor["user_id"], "cognito:groups": actor["role"]}
    if actor.get("technician_id"):
        claims["custom:technician_id"] = actor["technician_id"]
    if actor.get("zone"):
        claims["custom:zone"] = actor["zone"]
    method, resource = BRIDGE_ROUTES[body["type"]]
    inner = {
        "httpMethod": method,
        "resource": resource,
        "pathParameters": {"incident_id": body.get("incident_id")},
        "headers": {"X-Correlation-Id": body["correlation_id"]},
        "body": data or {},
        "requestContext": {"authorizer": {"claims": claims}},
    }
    try:
        ROUTES[(method, resource)](inner, deps, body["correlation_id"])
    except ApiError as err:
        # permite reintentar: 5xx, o 409 de estado (p. ej. el ack_token aún no se guardó) (F-21)
        if err.status >= 500 or isinstance(err, IncidentStateInvalid):
            deps["idempotency"].delete_item(Key={"pk": key})
        raise
    except Exception:
        deps["idempotency"].delete_item(Key={"pk": key})
        raise
    return {"processed": True, "duplicate": False}, {}


ROUTES = {
    ("POST", "/incidents/{incident_id}/ack"): ack,
    ("POST", "/incidents/{incident_id}/assign"): assign,
    ("POST", "/incidents/{incident_id}/resolve"): resolve,
    ("PUT", "/technicians/me/status"): technician_status,
    ("POST", "/ml/retrain"): retrain,
    ("POST", "/bridge/events"): bridge_event,
}
# Rutas que exigen JWT (todas menos el puente, que usa API key)
_JWT_ROUTES = {k for k in ROUTES if k[1] != "/bridge/events"}


def run(event: dict, deps: dict | None = None) -> dict:
    cid = correlation.from_api_event(event)
    try:
        resource = event.get("resource") or ""
        if resource.startswith("/v1/"):  # tolera rutas viejas con prefijo (el stage ya es v1)
            resource = resource[3:]
        key = (event.get("httpMethod"), resource)
        route = ROUTES.get(key)
        if route is None:
            raise NotFound("Ruta no implementada")
        if key in _JWT_ROUTES and not rbac.claims(event):
            raise Unauthenticated("Falta el JWT de Cognito")
        result = route(event, deps or _deps(), cid)
        data, meta = result[0], result[1]
        status = result[2] if len(result) > 2 else 200
        return response.ok(data, cid, meta=meta, status=status)
    except ApiError as err:
        return response.error(err, cid)
    except Exception:  # noqa: BLE001
        log.exception("Error no controlado (correlation_id=%s)", cid)
        return response.error(ApiError("Error interno"), cid)
