"""Lógica de negocio de api_lectura (RF-02.3, RF-03, RF-04, RF-05, RF-06.1, RF-07, RF-08, RF-11, RF-13, RF-16, RNF-08).

Todas las rutas GET de `contracts/openapi.yaml` con `x-lambda: api-lectura`, más `POST /auth/firebase-token`.
Rutas SIN prefijo `/v1`: el stage de API Gateway ya es `v1` (URL final `…/v1/me`, contratos.md §2).

- RBAC: el rol sale de `cognito:groups` (gana el de mayor precedencia) y se valida contra `x-roles` de cada ruta.
- Zona: `custom:zone` del usuario manda; un usuario global (`*` o sin zona) puede filtrar con `?zone=`.
  Pedir otra zona = 403; leer un recurso de otra zona = 404 (no se revela que existe). Igual que el modo demo del front.
- Paginación (`?limit=`/`?cursor=`) en las listas que el contrato pagina (`/machines`, `/incidents`). Las listas son
  chicas (100 máquinas, cientos de incidentes): se leen completas, se ordenan y se corta por offset, así el orden
  "severidad y antigüedad" es correcto entre páginas.
- `run(event, deps)` devuelve `(data, meta)`; el handler arma el envoltorio estándar.
Los clientes AWS/GCP se inyectan con `Deps` para probar sin AWS (moto) ni GCP (fakes).
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from arquifusion_shared import rbac
from arquifusion_shared.errors import Forbidden, NotFound, Unauthenticated, UpstreamUnavailable, ValidationError
from query_common import gcp, items

# Si el usuario está en varios grupos, gana el de mayor privilegio.
ROLE_PRECEDENCE = ("admin", "gerencia", "supervisor", "mantenimiento", "tecnico", "operador")
ALL_ROLES = frozenset(ROLE_PRECEDENCE)
ALL_ZONES = "*"
DEFAULT_LIMIT, MAX_LIMIT = 50, 100
MAX_SCAN_ITEMS = 5000  # tope de seguridad al leer una lista completa
TIMELINE_WINDOW_DAYS = 90  # MTBF/MTTR/disponibilidad (igual que el demo del front)
TELEMETRY_MAX_DAYS = 31
ETA_SPEED_KMH = 25  # frontend/src/lib/geo.ts y scoring (contratos.md §8.3)

ENUMS = {
    "machine_type": {"excavator", "mining_truck", "loader", "bulldozer", "drill"},
    "machine_status": {"operational", "stopped", "maintenance", "needs_intervention", "silent"},
    "severity": set(items.SEVERITY_RANK),
    "incident_status": {"detected", "assigned", "in_progress", "resolved", "closed", "abandoned"},
    "specialty": {"motor", "hidraulica", "electrica", "neumaticos"},
    "zone": {"norte", "sur", "este", "oeste"},
    "period": {"7d", "30d"},
}


# =========================================================================== dependencias
class Deps:
    """Tablas DynamoDB (por nombre de §1.1: `TABLE_<NOMBRE>`) y Firebase, creados bajo demanda y reutilizados."""

    def __init__(self, tables: dict | None = None, firebase: FirebaseService | None = None, env: dict | None = None):
        self._tables = dict(tables or {})
        self._firebase = firebase
        self.env = env if env is not None else os.environ

    def table(self, name: str):
        """`name` = sufijo de la tabla en minúsculas con `_` (machines, machine_state, …)."""
        if name not in self._tables:
            import boto3

            env_var = f"TABLE_{name.upper()}"
            if not self.env.get(env_var):
                raise RuntimeError(f"Falta la variable de entorno {env_var} (contratos.md §1.1)")
            self._tables[name] = boto3.resource("dynamodb").Table(self.env[env_var])
        return self._tables[name]

    @property
    def firebase(self) -> FirebaseService:
        if self._firebase is None:
            self._firebase = FirebaseService.from_env(self.env)
        return self._firebase

    @property
    def operation_id(self) -> str:
        return self.env.get("DEFAULT_OPERATION_ID") or "OP-01"


class FirebaseService:
    """Custom token (firma local) y registro del token FCM en Firestore `users/{uid}` (contratos.md §5)."""

    def __init__(self, sa_info: dict, signer, firestore: gcp.Firestore | None, now: Callable[[], float] | None = None):
        self.sa_info = sa_info
        self.signer = signer
        self.firestore = firestore
        self._now = now

    @classmethod
    def from_env(cls, env) -> FirebaseService:
        import boto3

        secret = env.get("FIREBASE_SECRET_NAME") or f"arquifusion/{env.get('STAGE', 'dev')}/gcp/service-account"
        try:
            sa = gcp.load_service_account(secret, boto3.client("secretsmanager"))
            fs = gcp.firestore_from_service_account(sa, env.get("GCP_PROJECT_ID") or None)
            return cls(sa, gcp.default_signer(sa), fs)
        except Exception as exc:  # secreto vacío, sin permiso o layer ausente
            raise UpstreamUnavailable("No se pudo cargar la service account de Firebase") from exc

    def mint(self, uid: str, claims: dict) -> str:
        now = self._now() if self._now else None
        return gcp.custom_token(self.sa_info, uid, claims, self.signer, now=now)

    def register_fcm_token(self, uid: str, profile: dict, fcm_token: str) -> None:
        fs = self.firestore
        write = fs.merge_array_union_write(f"users/{uid}", profile, "fcm_tokens", [fcm_token])
        fs.commit([write])


# =========================================================================== identidad y RBAC
class User:
    def __init__(self, user_id: str, email: str | None, role: str, zone: str | None, technician_id: str | None):
        self.user_id, self.email, self.role, self.zone, self.technician_id = user_id, email, role, zone, technician_id


def resolve_role(groups: set[str]) -> str | None:
    clean = {g.strip() for g in groups}
    return next((r for r in ROLE_PRECEDENCE if r in clean), None)


def current_user(event: dict) -> User:
    """Identidad según contratos.md §2.1. Requiere el ID token (el access token no trae email ni custom:*)."""
    claims = rbac.claims(event)
    if not claims:
        raise Unauthenticated("Falta el JWT de Cognito o no es válido")
    role = resolve_role(rbac.groups(event))
    if role is None:
        raise Forbidden("El usuario no pertenece a ningún grupo de la plataforma")
    zone = (claims.get("custom:zone") or "").strip()
    if not zone and role in rbac.ZONE_ROLES:  # F-11: sin zona = Forbidden; solo `*` es global
        raise Forbidden("El usuario no tiene zona asignada (custom:zone)")
    tech = (claims.get("custom:technician_id") or "").strip()
    return User(
        # user_id = cognito:username (u-tec-07): el mismo id de Firestore, Pub/Sub y Technicians.user_id
        user_id=claims.get("cognito:username") or claims.get("sub"),
        email=claims.get("email"),
        role=role,
        zone=None if zone in ("", ALL_ZONES) else zone,
        technician_id=(tech or None) if role == "tecnico" else None,
    )


def effective_zone(user: User, requested: str | None) -> str | None:
    """La zona del usuario manda; un usuario global puede filtrar por cualquiera."""
    requested = (requested or "").strip() or None
    if requested and requested not in ENUMS["zone"]:
        raise ValidationError("zone inválida", [{"field": "zone", "issue": "enum"}])
    if user.zone and requested and requested != user.zone:
        raise Forbidden(f"Tu usuario solo ve la zona {user.zone}")
    return user.zone or requested


def _visible(user: User, zone: str | None) -> bool:
    return not user.zone or zone == user.zone


# =========================================================================== utilidades de request
def _qs(event: dict) -> dict:
    return {k: v for k, v in (event.get("queryStringParameters") or {}).items() if v not in (None, "")}


def _path(event: dict, name: str) -> str:
    value = (event.get("pathParameters") or {}).get(name)
    if not value:
        raise ValidationError(f"Falta {name} en la ruta", [{"field": name, "issue": "required"}])
    return value


def _enum(q: dict, field: str, enum: str, default: str | None = None) -> str | None:
    value = q.get(field, default)
    if value is not None and value not in ENUMS[enum]:
        raise ValidationError(f"{field} inválido", [{"field": field, "issue": "enum"}])
    return value


def _bool(q: dict, field: str) -> bool | None:
    raw = q.get(field)
    if raw is None:
        return None
    if raw.lower() in ("true", "1"):
        return True
    if raw.lower() in ("false", "0"):
        return False
    raise ValidationError(f"{field} debe ser true o false", [{"field": field, "issue": "boolean"}])


def _limit(q: dict) -> int:
    try:
        limit = int(q.get("limit", DEFAULT_LIMIT))
    except ValueError:
        limit = -1
    if not 1 <= limit <= MAX_LIMIT:
        raise ValidationError("limit debe estar entre 1 y 100", [{"field": "limit", "issue": "range"}])
    return limit


def _offset(q: dict) -> int:
    cursor = q.get("cursor")
    if not cursor:
        return 0
    try:
        offset = int(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode())
    except (ValueError, binascii.Error, UnicodeDecodeError):
        offset = -1
    if offset < 0:
        raise ValidationError("cursor inválido", [{"field": "cursor", "issue": "invalid"}])
    return offset


def _paginate(rows: list, q: dict) -> tuple[list, dict]:
    limit, start = _limit(q), _offset(q)
    page = rows[start : start + limit]
    nxt = start + limit
    cursor = base64.urlsafe_b64encode(str(nxt).encode()).decode().rstrip("=") if nxt < len(rows) else None
    return page, {"count": len(page), "next_cursor": cursor}


def _parse_ts(value: str, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        raise ValidationError(f"{field} debe ser ISO 8601", [{"field": field, "issue": "format"}]) from None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(UTC)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# =========================================================================== lectura DynamoDB
def _read_all(fn: Callable[..., dict], **kwargs) -> list[dict]:
    out: list[dict] = []
    while True:
        page = fn(**kwargs)
        out.extend(page.get("Items", []))
        if "LastEvaluatedKey" not in page or len(out) >= MAX_SCAN_ITEMS:
            return out
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _query(table, index: str | None, key: str, value: str, **kwargs) -> list[dict]:
    from boto3.dynamodb.conditions import Key

    if index:
        kwargs["IndexName"] = index
    return _read_all(table.query, KeyConditionExpression=Key(key).eq(value), **kwargs)


def _scan_meta(table) -> list[dict]:
    from boto3.dynamodb.conditions import Attr

    return _read_all(table.scan, FilterExpression=Attr("sk").eq("META"))


def _machine_item(deps: Deps, user: User, machine_id: str) -> dict:
    item = deps.table("machines").get_item(Key={"pk": f"{deps.operation_id}#{machine_id}", "sk": "META"}).get("Item")
    if not item or not _visible(user, items.machine_zone(item)):
        raise NotFound(f"No existe la máquina {machine_id}")
    return item


def _insight(deps: Deps, kind: str, sk: str = "LATEST") -> dict | None:
    return deps.table("insights").get_item(Key={"pk": kind, "sk": sk}).get("Item")


def _insight_meta(item: dict | None) -> dict:
    return {"generated_at": (item or {}).get("generated_at")}


def _insight_rows(deps: Deps, kind: str) -> tuple[list[dict], dict]:
    """Insight de tipo lista. Si AnalisisDiario aún no corrió: lista vacía (no es un error para el front)."""
    item = _insight(deps, kind)
    rows = items.plain(item.get("data")) if item else None
    return (rows if isinstance(rows, list) else []), _insight_meta(item)


def _insight_object(deps: Deps, kind: str, sk: str = "LATEST", what: str = "") -> tuple[dict, dict]:
    item = _insight(deps, kind, sk)
    if not item or item.get("data") is None:
        raise NotFound(f"Aún no hay {what or kind}: lo genera el workflow AnalisisDiario")
    return items.plain(item["data"]), _insight_meta(item)


# =========================================================================== sesión
def get_me(event: dict, deps: Deps, user: User):
    """MeResponse.data (openapi.yaml)."""
    return {
        "user_id": user.user_id,
        "email": user.email,
        "role": user.role,
        "zone": user.zone,
        "technician_id": user.technician_id,
    }, {}


def post_firebase_token(event: dict, deps: Deps, user: User):
    """Custom token con claims role/zone/technician_id (§2.1) y, si viene, arrayUnion del token FCM (§5)."""
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        raise ValidationError("El cuerpo no es JSON válido") from None
    if not isinstance(body, dict):
        raise ValidationError("El cuerpo debe ser un objeto JSON")
    fcm_token = body.get("fcm_token")
    if fcm_token is not None and (not isinstance(fcm_token, str) or not 0 < len(fcm_token) <= 4096):
        raise ValidationError("fcm_token inválido", [{"field": "fcm_token", "issue": "string"}])

    claims = {"role": user.role, "zone": user.zone, "technician_id": user.technician_id}
    firebase = deps.firebase
    try:
        token = firebase.mint(user.user_id, claims)
    except Exception as exc:
        raise UpstreamUnavailable("No se pudo firmar el token de Firebase") from exc

    meta: dict[str, Any] = {}
    if fcm_token:
        # En users/{uid} la zona global se guarda como "*": notify_bridge filtra `zone in [target.zone, "*"]` (§4).
        profile = {
            **claims,
            "zone": user.zone or ALL_ZONES,
            "user_id": user.user_id,
            "updated_at": _iso(datetime.now(UTC)),
        }
        try:
            firebase.register_fcm_token(user.user_id, profile, fcm_token)
            meta["fcm_registered"] = True
        except Exception:
            # El push es secundario: el login a Firestore (mapa, chat) no debe caerse por esto.
            from arquifusion_shared.observability import logger

            logger.exception("fcm_token_no_registrado", extra={"user_id": user.user_id})
            meta["fcm_registered"] = False
    return {"firebase_token": token, "expires_in": gcp.CUSTOM_TOKEN_TTL_S}, meta


# =========================================================================== flota
def list_machines(event: dict, deps: Deps, user: User):
    q = _qs(event)
    zone = effective_zone(user, q.get("zone"))
    mtype = _enum(q, "type", "machine_type")
    status = _enum(q, "status", "machine_status")
    severity = _enum(q, "severity", "severity")
    table = deps.table("machines")
    raw = _query(table, "by_zone", "zone", zone) if zone else _scan_meta(table)
    rows = [
        items.machine(i)
        for i in raw
        if i.get("sk", "META") == "META"
        and i.get("machine_id")
        and (not mtype or i.get("type") == mtype)
        and (not status or i.get("status") == status)
        and (not severity or i.get("severity") == severity)
    ]
    rows.sort(key=lambda m: m["machine_id"])
    return _paginate(rows, q)


def get_machine(event: dict, deps: Deps, user: User):
    machine_id = _path(event, "machine_id")
    item = _machine_item(deps, user, machine_id)
    detail = items.machine(item, detail=True)
    if not detail.get("latest_reading"):
        last = deps.table("machine_state").get_item(Key={"pk": machine_id, "sk": "LAST"}).get("Item")
        detail["latest_reading"] = items.plain(last.get("reading")) if last else None
    return detail, {}


def get_telemetry(event: dict, deps: Deps, user: User):
    """Agregados por hora de `machine-state` (`AGG#1h#YYYY-MM-DDTHH`, escritos por procesar).

    `procesar` solo guarda agregados de 1 h: con `resolution=1m` se responden buckets de 1 h y
    `meta.resolution` dice la resolución real (decisión documentada en api_lectura/README.md).
    """
    machine_id = _path(event, "machine_id")
    q = _qs(event)
    for field in ("from", "to"):
        if field not in q:
            raise ValidationError(f"Falta {field}", [{"field": field, "issue": "required"}])
    start, end = _parse_ts(q["from"], "from"), _parse_ts(q["to"], "to")
    if start >= end:
        raise ValidationError("from debe ser anterior a to", [{"field": "from", "issue": "invalid_range"}])
    if end - start > timedelta(days=TELEMETRY_MAX_DAYS):
        raise ValidationError(f"El rango máximo es {TELEMETRY_MAX_DAYS} días", [{"field": "from", "issue": "range"}])
    if q.get("resolution", "1m") not in ("1m", "1h"):
        raise ValidationError("resolution inválida", [{"field": "resolution", "issue": "enum"}])
    _machine_item(deps, user, machine_id)

    from boto3.dynamodb.conditions import Key

    lo, hi = f"AGG#1h#{start.strftime('%Y-%m-%dT%H')}", f"AGG#1h#{end.strftime('%Y-%m-%dT%H')}"
    raw = _read_all(
        deps.table("machine_state").query,
        KeyConditionExpression=Key("pk").eq(machine_id) & Key("sk").between(lo, hi),
    )
    points = []
    for it in sorted(raw, key=lambda x: x["sk"]):
        hour = it["sk"].removeprefix("AGG#1h#")
        vars_ = items.plain(it.get("vars") or {})
        point: dict[str, Any] = {"bucket_start": f"{hour}:00:00Z"}
        for var in ("temperature_c", "vibration_mm_s", "pressure_bar", "fuel_rate_lph"):
            agg = vars_.get(var) or {}
            point[var] = {"min": agg.get("min"), "avg": agg.get("avg"), "max": agg.get("max")}
        health = vars_.get("health_score") or {}
        point["health_score"] = health.get("avg", items.plain(it.get("health_score")))
        points.append(point)
    return points, {"resolution": "1h", "count": len(points)}


def _incident_summary(inc: dict) -> str:
    cause = ((inc.get("ai_diagnosis") or {}).get("probable_cause")) or "Diagnóstico pendiente"
    return f"{str(inc.get('severity', '')).upper()} · {cause} ({inc.get('status')})"


def _downtime_hours(inc: dict) -> float:
    if inc.get("downtime_minutes") is not None:
        return float(inc["downtime_minutes"]) / 60
    if inc.get("resolved_at") and inc.get("detected_at"):
        try:
            delta = _parse_ts(inc["resolved_at"], "resolved_at") - _parse_ts(inc["detected_at"], "detected_at")
            return max(0.0, delta.total_seconds() / 3600)
        except ValidationError:
            return 0.0
    return 0.0


def _at(value: str | None) -> str | None:
    if not value:
        return None
    return f"{value}T00:00:00Z" if len(value) == 10 else value


def get_timeline(event: dict, deps: Deps, user: User, now: datetime | None = None):
    """Incidentes (by_machine), mantenimientos (`maintenance-records`) y anomalías recientes.

    Incluye MTBF/MTTR/disponibilidad.
    """
    machine_id = _path(event, "machine_id")
    _machine_item(deps, user, machine_id)
    now = now or datetime.now(UTC)
    since = _iso(now - timedelta(days=TIMELINE_WINDOW_DAYS))

    incidents = [
        items.plain(i)
        for i in _query(deps.table("incidents"), "by_machine", "machine_id", machine_id)
        if i.get("sk", "META") == "META"
    ]
    records = [items.plain(r) for r in _query(deps.table("maintenance_records"), None, "pk", machine_id)]
    from boto3.dynamodb.conditions import Key

    anomalies = (
        deps.table("anomalies")
        .query(
            KeyConditionExpression=Key("pk").eq(machine_id) & Key("sk").gte(since),
            ScanIndexForward=False,
            Limit=50,
        )
        .get("Items", [])
    )

    events = [
        {
            "at": i.get("detected_at"),
            "kind": "incident",
            "ref_id": i.get("incident_id"),
            "summary": _incident_summary(i),
        }
        for i in incidents
    ]
    for r in records:
        kind = r.get("type") if r.get("type") in ("preventive", "corrective") else "preventive"
        comps = ", ".join(f"{c.get('component_id')} x{c.get('quantity', 1)}" for c in r.get("components") or [])
        label = "Preventivo" if kind == "preventive" else "Correctivo"
        events.append(
            {
                "at": _at(r.get("performed_at")),
                "kind": kind,
                "ref_id": r.get("record_id") or r.get("sk"),
                "summary": f"{label}: {comps or r.get('notes') or 'inspección'}",
            }
        )
    for a in (items.plain(x) for x in anomalies):
        factors = ", ".join(f"{f.get('variable')} z={f.get('z_score')}" for f in a.get("top_factors") or [])
        events.append(
            {
                "at": a.get("detected_at") or a.get("sk", "").split("#")[0],
                "kind": "anomaly",
                "ref_id": a.get("anomaly_id") or a.get("sk"),
                "summary": f"{str(a.get('severity', '')).upper()} · {factors or 'Anomalía detectada'}",
            }
        )
    events = [e for e in events if e["at"]]
    events.sort(key=lambda e: e["at"], reverse=True)

    window_h = TIMELINE_WINDOW_DAYS * 24
    closed = [
        i for i in incidents if i.get("status") in ("resolved", "closed") and (i.get("detected_at") or "") >= since
    ]
    downtime_h = sum(_downtime_hours(i) for i in closed)
    n = max(1, len(closed))
    kpis = {
        "mtbf_hours": round(window_h / n, 1),
        "mttr_hours": round(downtime_h / n, 1),
        "availability_pct": round(min(100.0, max(0.0, 100 - downtime_h / window_h * 100)), 1),
    }
    return {"events": events, "kpis": kpis}, {}


# =========================================================================== incidentes
def _incident_sort_key(i: dict):
    """Abiertos primero, luego severidad desc.

    Abiertos del más antiguo al más nuevo; cerrados del más nuevo al más antiguo.
    """
    closed = i.get("status") == "closed"
    ts = i.get("detected_at") or ""
    ts_key = tuple(-ord(c) for c in ts) if closed else tuple(ord(c) for c in ts)
    return (closed, -items.SEVERITY_RANK.get(i.get("severity"), 0), ts_key)


def list_incidents(event: dict, deps: Deps, user: User):
    q = _qs(event)
    zone = effective_zone(user, q.get("zone"))
    status = _enum(q, "status", "incident_status")
    severity = _enum(q, "severity", "severity")
    machine_id, parent = q.get("machine_id"), q.get("parent_incident_id")
    table = deps.table("incidents")
    if machine_id:
        raw = _query(table, "by_machine", "machine_id", machine_id)
    elif status:
        raw = _query(table, "by_status", "status", status)
    else:
        raw = _scan_meta(table)
    rows = [
        items.incident(i)
        for i in raw
        if i.get("sk", "META") == "META"
        and i.get("incident_id")
        and (not zone or i.get("zone") == zone)
        and (not status or i.get("status") == status)
        and (not severity or i.get("severity") == severity)
        and (not parent or i.get("parent_incident_id") == parent)
    ]
    rows.sort(key=_incident_sort_key)
    return _paginate(rows, q)


def get_incident(event: dict, deps: Deps, user: User):
    incident_id = _path(event, "incident_id")
    item = deps.table("incidents").get_item(Key={"pk": f"INC#{incident_id}", "sk": "META"}).get("Item")
    if not item or not _visible(user, item.get("zone")):
        raise NotFound(f"No existe el incidente {incident_id}")
    return items.incident(item), {}


# =========================================================================== técnicos
def haversine_km(a: dict, b: dict) -> float:
    r = 6371
    la1, lo1, la2, lo2 = (math.radians(float(x)) for x in (a["lat"], a["lon"], b["lat"], b["lon"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def eta_minutes(a: dict, b: dict) -> int:
    """Igual que `etaMinutes` de frontend/src/lib/geo.ts: 25 km/h + 2 min, mínimo 1."""
    return max(1, round(haversine_km(a, b) / ETA_SPEED_KMH * 60 + 2))


def list_technicians(event: dict, deps: Deps, user: User):
    q = _qs(event)
    available = _bool(q, "available")
    specialty = _enum(q, "specialty", "specialty")
    target = None
    if q.get("machine_id"):
        m = items.machine(_machine_item(deps, user, q["machine_id"]))
        target = m.get("location")
    table = deps.table("technicians")
    raw = _query(table, "by_zone", "zone", user.zone) if user.zone else _scan_meta(table)
    rows = []
    for it in raw:
        if it.get("sk", "META") != "META" or not it.get("technician_id"):
            continue
        t = items.technician(it)
        if available is not None and t["available"] != available:
            continue
        if specialty and specialty not in t["specialties"]:
            continue
        t["eta_minutes"] = eta_minutes(t["location"], target) if target and t["location"] else None
        rows.append(t)
    rows.sort(key=lambda t: (t["eta_minutes"] if t["eta_minutes"] is not None else 1e9, t["technician_id"]))
    return rows, {"count": len(rows)}


# =========================================================================== repuestos y mantenimiento
def list_inventory(event: dict, deps: Deps, user: User):
    q = _qs(event)
    alert = q.get("alert")
    if alert is not None and alert not in ("low_stock", "overstock"):
        raise ValidationError("alert inválido", [{"field": "alert", "issue": "enum"}])
    table = deps.table("inventory")
    if q.get("warehouse_id"):
        raw = _query(table, None, "pk", q["warehouse_id"])
    else:
        raw = _read_all(table.scan)
    rows = [items.inventory(i) for i in raw if i.get("component_id") and _visible(user, i.get("zone"))]
    rows = [r for r in rows if not alert or r["alert"] == alert]
    rows.sort(key=lambda r: (r["warehouse_id"], r["component_id"]))
    return rows, {"count": len(rows)}


def parts_ranking(event: dict, deps: Deps, user: User):
    return _insight_rows(deps, "parts_ranking")


def _warehouse_zones(deps: Deps) -> dict[str, str]:
    return {w.get("warehouse_id") or w["pk"]: w.get("zone") for w in _read_all(deps.table("warehouses").scan)}


def parts_forecast(event: dict, deps: Deps, user: User):
    q = _qs(event)
    horizon = q.get("horizon_days", "30")
    if horizon not in ("7", "30", "90"):
        raise ValidationError("horizon_days debe ser 7, 30 o 90", [{"field": "horizon_days", "issue": "enum"}])
    rows, meta = _insight_rows(deps, f"parts_forecast#{horizon}")
    if q.get("warehouse_id"):
        rows = [r for r in rows if r.get("warehouse_id") == q["warehouse_id"]]
    if user.zone:
        zones = _warehouse_zones(deps)
        rows = [r for r in rows if (r.get("zone") or zones.get(r.get("warehouse_id"))) == user.zone]
    return rows, meta


def maintenance_plan(event: dict, deps: Deps, user: User):
    q = _qs(event)
    zone = effective_zone(user, q.get("zone"))
    flag = q.get("flag")
    if flag is not None and flag not in ("overdue", "unnecessary"):
        raise ValidationError("flag inválido", [{"field": "flag", "issue": "enum"}])
    rows, meta = _insight_rows(deps, "maintenance_plan")
    rows = [r for r in rows if (not zone or r.get("zone") == zone) and (not flag or r.get("flag") == flag)]
    return rows, meta


# =========================================================================== analítica
def _zoned_rows(event: dict, deps: Deps, user: User, prefix: str):
    q = _qs(event)
    zone = effective_zone(user, q.get("zone"))
    period = _enum(q, "period", "period", "7d")
    rows, meta = _insight_rows(deps, f"{prefix}#{period}")
    return [r for r in rows if not zone or r.get("zone") == zone], meta


def analytics_fuel(event: dict, deps: Deps, user: User):
    return _zoned_rows(event, deps, user, "fuel")


def analytics_productivity(event: dict, deps: Deps, user: User):
    return _zoned_rows(event, deps, user, "productivity")


def analytics_kpis(event: dict, deps: Deps, user: User):
    """`kpis#<period>`: `sk = LATEST` (toda la flota) o `LATEST#<zone>` (contratos.md §9, insights)."""
    q = _qs(event)
    zone = effective_zone(user, q.get("zone"))
    period = _enum(q, "period", "period", "7d")
    data, meta = _insight_object(deps, f"kpis#{period}", f"LATEST#{zone}" if zone else "LATEST", "KPIs")
    return data, {**meta, "zone": zone}


def _require_global(user: User, what: str) -> None:
    """F-15: el reporte y el modelo ML son de toda la flota; un usuario acotado a una zona no los ve."""
    if user.zone:
        raise Forbidden(f"{what} es global: tu usuario solo ve la zona {user.zone}")


def reports_latest(event: dict, deps: Deps, user: User):
    _require_global(user, "El reporte")
    q = _qs(event)
    rtype = q.get("type", "daily")
    if rtype not in ("daily", "weekly"):
        raise ValidationError("type inválido", [{"field": "type", "issue": "enum"}])
    data, meta = _insight_object(deps, f"report#{rtype}", what="reporte")
    data.setdefault("generated_at", meta.get("generated_at"))
    return data, meta


def ml_model(event: dict, deps: Deps, user: User):
    _require_global(user, "El modelo")
    return _insight_object(deps, "ml_model", what="modelo entrenado")


# =========================================================================== rutas
Handler = Callable[[dict, Deps, User], tuple[Any, dict]]
_O, _T, _M, _S, _A, _G = "operador", "tecnico", "mantenimiento", "supervisor", "admin", "gerencia"

# (método, recurso de API Gateway) -> (función, x-roles del OpenAPI). Recursos SIN /v1 (stage v1).
ROUTES: dict[tuple[str, str], tuple[Handler, frozenset[str]]] = {
    ("GET", "/me"): (get_me, ALL_ROLES),
    ("POST", "/auth/firebase-token"): (post_firebase_token, ALL_ROLES),
    ("GET", "/machines"): (list_machines, ALL_ROLES),
    ("GET", "/machines/{machine_id}"): (get_machine, ALL_ROLES),
    ("GET", "/machines/{machine_id}/telemetry"): (get_telemetry, frozenset({_T, _M, _S, _A, _G})),
    ("GET", "/machines/{machine_id}/timeline"): (get_timeline, frozenset({_T, _M, _S, _A, _G})),
    ("GET", "/incidents"): (list_incidents, ALL_ROLES),
    ("GET", "/incidents/{incident_id}"): (get_incident, ALL_ROLES),
    ("GET", "/technicians"): (list_technicians, frozenset({_M, _S, _A})),
    ("GET", "/inventory"): (list_inventory, frozenset({_M, _S, _A})),
    ("GET", "/parts/ranking"): (parts_ranking, frozenset({_M, _S, _A})),
    ("GET", "/parts/forecast"): (parts_forecast, frozenset({_M, _A})),
    ("GET", "/maintenance/plan"): (maintenance_plan, frozenset({_M, _S, _A})),
    ("GET", "/analytics/fuel"): (analytics_fuel, frozenset({_S, _A, _G})),
    ("GET", "/analytics/productivity"): (analytics_productivity, frozenset({_S, _A, _G})),
    ("GET", "/analytics/kpis"): (analytics_kpis, frozenset({_S, _A, _G})),
    ("GET", "/reports/latest"): (reports_latest, frozenset({_A, _G, _S})),
    ("GET", "/ml/model"): (ml_model, frozenset({_A, _M})),
}

_deps: Deps | None = None


def default_deps() -> Deps:
    global _deps
    if _deps is None:
        _deps = Deps()
    return _deps


def run(event: dict, deps: Deps | None = None) -> tuple[Any, dict]:
    key = (event.get("httpMethod", ""), event.get("resource", ""))
    route = ROUTES.get(key)
    if route is None:
        raise NotFound(f"Ruta no implementada: {key[0]} {key[1]}")
    fn, roles = route
    user = current_user(event)
    if user.role not in roles:
        raise Forbidden(f"El rol {user.role} no puede usar esta operación")
    return fn(event, deps or default_deps(), user)
