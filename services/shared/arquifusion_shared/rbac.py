"""RBAC por grupo de Cognito y zona (RNF-08, contratos.md §2.1). Se valida DENTRO de la Lambda además del authorizer."""
from .errors import Forbidden

ROLES = {"operador", "tecnico", "mantenimiento", "supervisor", "admin", "gerencia"}

# Si el usuario trae varios grupos, gana el de mayor precedencia (contratos.md §2.1).
# Debe coincidir con la `precedence` de los grupos de Cognito en infra/base (0 = mayor).
ROLE_PRECEDENCE = ("admin", "gerencia", "supervisor", "mantenimiento", "tecnico", "operador")

# Zona del usuario en `custom:zone`: "*" o ausente = todas.
GLOBAL_ZONE = "*"


def claims(event: dict) -> dict:
    return (event.get("requestContext") or {}).get("authorizer", {}).get("claims", {}) or {}


def groups(event: dict) -> set[str]:
    raw = claims(event).get("cognito:groups", "")
    if isinstance(raw, str):
        # API Gateway REST entrega "a,b" (o "[a b]" en algunos casos)
        raw = raw.strip("[]").replace(" ", ",").split(",")
    return {g.strip() for g in raw if g and g.strip()}


def role(event: dict) -> str | None:
    """Rol resuelto por precedencia (`None` si no tiene ningún grupo conocido)."""
    mine = groups(event)
    return next((r for r in ROLE_PRECEDENCE if r in mine), None)


def user_id(event: dict) -> str | None:
    """`cognito:username` = user_id de la plataforma (u-tec-07)."""
    return claims(event).get("cognito:username")


def technician_id(event: dict) -> str | None:
    """`custom:technician_id` (solo usuarios del grupo `tecnico`, #8)."""
    return claims(event).get("custom:technician_id") or None


def zone(event: dict) -> str | None:
    """Zona del usuario; `None` si es global (`*` o sin atributo)."""
    value = (claims(event).get("custom:zone") or "").strip().lower()
    return None if value in ("", GLOBAL_ZONE) else value


def actor(event: dict) -> dict:
    """Actor de TRZ-02 para eventos y Step Functions (contratos.md §3)."""
    return {"type": "user", "user_id": user_id(event), "role": role(event)}


def require(event: dict, *allowed: str, zone: str | None = None) -> None:
    """Exige uno de los roles `allowed`. Si se pasa `zone` (zona del recurso), además exige que el
    usuario sea global o de esa zona (#27)."""
    if not groups(event) & set(allowed):
        raise Forbidden("El rol no tiene permiso para esta operación")
    if zone is not None:
        require_zone(event, zone)


def require_zone(event: dict, resource_zone: str | None) -> None:
    user_zone = zone(event)
    if user_zone is not None and resource_zone and user_zone != str(resource_zone).lower():
        raise Forbidden("El recurso pertenece a otra zona")
