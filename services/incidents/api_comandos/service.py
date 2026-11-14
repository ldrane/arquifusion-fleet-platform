"""Lógica de negocio de api_comandos (RF-06.4, RF-11.1, RF-16.5).

Comandos implementados: ack, assign, resolve y technicians/me/status.
Pendientes: ml/retrain y bridge/events.

Cada comando valida rol, lee el incidente de DynamoDB y avisa a Step Functions
con SendTaskSuccess usando el token guardado en el ítem META del incidente.
Los clientes AWS se inyectan (deps) para poder probar sin AWS.
"""
import json
import logging
import os
from decimal import Decimal

from arquifusion_shared import correlation, rbac, response
from arquifusion_shared.errors import (
    ApiError,
    IncidentStateInvalid,
    NotFound,
    UpstreamUnavailable,
    ValidationError,
)

log = logging.getLogger(__name__)

# Si Step Functions responde con alguno de estos códigos, el token ya se usó o venció.
_TOKEN_MUERTO = {"InvalidToken", "TaskDoesNotExist", "TaskTimedOut"}


# ---------- utilidades ----------

def _default_deps() -> dict:
    import boto3

    ddb = boto3.resource("dynamodb")
    return {
        "incidents": ddb.Table(os.environ["INCIDENTS_TABLE"]),
        "technicians": ddb.Table(os.environ["TECHNICIANS_TABLE"]),
        "sfn": boto3.client("stepfunctions"),
    }


def _code(exc: Exception) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "")


def _body(event: dict) -> dict:
    try:
        body = json.loads(event.get("body") or "{}")
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


def _get_incident(deps: dict, incident_id: str) -> dict:
    item = deps["incidents"].get_item(Key={"pk": f"INC#{incident_id}", "sk": "META"}).get("Item")
    if not item:
        raise NotFound(f"Incidente {incident_id} no existe")
    return item


def _require_status(item: dict, allowed: set[str]) -> None:
    if item.get("status") not in allowed:
        raise IncidentStateInvalid(f"El incidente está en estado '{item.get('status')}'")


def _token(item: dict, name: str) -> str:
    token = item.get(name)
    if not token:
        raise IncidentStateInvalid("El incidente no está esperando esta acción")
    return token


def _send_success(sfn, token: str, output: dict) -> None:
    try:
        sfn.send_task_success(taskToken=token, output=json.dumps(output, default=str))
    except Exception as exc:  # noqa: BLE001 - botocore ClientError
        if _code(exc) in _TOKEN_MUERTO:
            raise IncidentStateInvalid("El incidente ya no está esperando esta acción") from exc
        raise UpstreamUnavailable("No se pudo contactar a Step Functions") from exc


# ---------- comandos ----------

def ack(event: dict, deps: dict, cid: str) -> dict:
    rbac.require(event, "tecnico", "mantenimiento")
    incident_id = _path(event, "incident_id")
    body = _body(event)
    decision = body.get("decision")
    if decision not in ("accept", "reject"):
        raise ValidationError("decision debe ser accept o reject", [{"field": "decision"}])

    item = _get_incident(deps, incident_id)
    _require_status(item, {"assigned"})
    _send_success(
        deps["sfn"],
        _token(item, "ack_token"),
        {
            "decision": decision,
            "reason": body.get("reason"),
            "technician_id": item.get("assigned_technician_id"),
            "correlation_id": cid,
        },
    )
    return {"incident_id": incident_id, "decision": decision}


def assign(event: dict, deps: dict, cid: str) -> dict:
    rbac.require(event, "mantenimiento", "supervisor", "admin")
    incident_id = _path(event, "incident_id")
    body = _body(event)
    technician_id = body.get("technician_id")
    if not isinstance(technician_id, str) or not technician_id:
        raise ValidationError("technician_id es obligatorio", [{"field": "technician_id"}])

    tech = deps["technicians"].get_item(Key={"pk": f"TECH#{technician_id}", "sk": "META"}).get("Item")
    if not tech:
        raise NotFound(f"Técnico {technician_id} no existe")

    item = _get_incident(deps, incident_id)
    _require_status(item, {"detected", "assigned"})
    _send_success(
        deps["sfn"],
        _token(item, "ack_token"),
        {
            "decision": "reassign",
            "technician_id": technician_id,
            "reason": body.get("reason"),
            "correlation_id": cid,
        },
    )
    return {"incident_id": incident_id, "technician_id": technician_id}


def resolve(event: dict, deps: dict, cid: str) -> dict:
    rbac.require(event, "tecnico", "mantenimiento")
    incident_id = _path(event, "incident_id")
    body = _body(event)

    notes = body.get("resolution_notes")
    if not isinstance(notes, str) or not notes.strip():
        raise ValidationError("resolution_notes es obligatorio", [{"field": "resolution_notes"}])
    if len(notes) > 2000:
        raise ValidationError("resolution_notes excede 2000 caracteres", [{"field": "resolution_notes"}])
    components = body.get("components_replaced", [])
    if not isinstance(components, list) or not all(isinstance(c, str) for c in components):
        raise ValidationError("components_replaced debe ser lista de textos", [{"field": "components_replaced"}])
    cost = body.get("cost_usd")
    if cost is not None and (isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0):
        raise ValidationError("cost_usd debe ser un número >= 0", [{"field": "cost_usd"}])

    item = _get_incident(deps, incident_id)
    _require_status(item, {"in_progress"})
    _send_success(
        deps["sfn"],
        _token(item, "resolve_token"),
        {
            "resolution_notes": notes,
            "components_replaced": components,
            "cost_usd": cost,
            "correlation_id": cid,
        },
    )
    return {"incident_id": incident_id, "status": "resolved"}


def technician_status(event: dict, deps: dict, cid: str) -> dict:
    rbac.require(event, "tecnico")
    technician_id = rbac.claims(event).get("custom:technician_id")
    if not technician_id:
        raise ValidationError("El usuario no tiene technician_id asociado")

    body = _body(event)
    updates = {}
    if "available" in body:
        if not isinstance(body["available"], bool):
            raise ValidationError("available debe ser true o false", [{"field": "available"}])
        updates["available"] = body["available"]
    if "location" in body:
        if not isinstance(body["location"], dict):
            raise ValidationError("location debe ser un objeto", [{"field": "location"}])
        updates["location"] = body["location"]
    if not updates:
        raise ValidationError("Envía available y/o location")

    # DynamoDB no acepta float: se convierten a Decimal solo para guardar.
    to_store = json.loads(json.dumps(updates), parse_float=Decimal)
    names = {f"#{k}": k for k in to_store}
    values = {f":{k}": v for k, v in to_store.items()}
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in to_store)
    try:
        deps["technicians"].update_item(
            Key={"pk": f"TECH#{technician_id}", "sk": "META"},
            UpdateExpression=expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(pk)",
        )
    except Exception as exc:  # noqa: BLE001
        if _code(exc) == "ConditionalCheckFailedException":
            raise NotFound(f"Técnico {technician_id} no existe") from exc
        raise
    return {"technician_id": technician_id, **updates}


ROUTES = {
    ("POST", "/v1/incidents/{incident_id}/ack"): ack,
    ("POST", "/v1/incidents/{incident_id}/assign"): assign,
    ("POST", "/v1/incidents/{incident_id}/resolve"): resolve,
    ("PUT", "/v1/technicians/me/status"): technician_status,
}


def run(event: dict, deps: dict | None = None) -> dict:
    cid = correlation.from_api_event(event)
    try:
        route = ROUTES.get((event.get("httpMethod"), event.get("resource")))
        if route is None:
            raise NotFound("Ruta no implementada")
        return response.ok(route(event, deps or _default_deps(), cid), cid)
    except ApiError as err:
        return response.error(err, cid)
    except Exception:  # noqa: BLE001
        log.exception("Error no controlado (correlation_id=%s)", cid)
        return response.error(ApiError("Error interno"), cid)
