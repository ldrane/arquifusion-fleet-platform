"""Lógica de negocio de api_lectura. Funciones puras, testeables sin AWS.

H0: GET /v1/me. El resto de GET /v1/* llega en H1.
"""
from __future__ import annotations

from arquifusion_shared import rbac
from arquifusion_shared.errors import Forbidden, NotFound, Unauthenticated

# Si el usuario está en varios grupos, gana el de mayor privilegio.
ROLE_PRECEDENCE = ("admin", "gerencia", "supervisor", "mantenimiento", "tecnico", "operador")
ALL_ZONES = "*"


def resolve_role(groups: set[str]) -> str | None:
    clean = {g.strip() for g in groups}
    return next((r for r in ROLE_PRECEDENCE if r in clean), None)


def get_me(event: dict) -> dict:
    """MeResponse.data (openapi.yaml). Requiere el ID token: el access token no trae email ni custom:zone."""
    claims = rbac.claims(event)
    if not claims:
        raise Unauthenticated("Falta el JWT de Cognito o no es válido")
    role = resolve_role(rbac.groups(event))
    if role is None:
        raise Forbidden("El usuario no pertenece a ningún grupo de la plataforma")
    zone = (claims.get("custom:zone") or "").strip()
    return {
        # user_id = cognito:username (ej. u-tec-07): el mismo id de Firestore, Pub/Sub y Technicians.user_id
        "user_id": claims.get("cognito:username") or claims.get("sub"),
        "email": claims.get("email"),
        "role": role,
        "zone": None if zone in ("", ALL_ZONES) else zone,
    }


# (método, recurso de API Gateway) -> función
ROUTES = {
    ("GET", "/v1/me"): get_me,
}


def run(event: dict):
    key = (event.get("httpMethod", ""), event.get("resource", ""))
    route = ROUTES.get(key)
    if route is None:
        raise NotFound(f"Ruta no implementada: {key[0]} {key[1]}")
    return route(event)
