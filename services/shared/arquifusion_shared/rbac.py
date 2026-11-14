"""RBAC por grupo de Cognito y zona (RNF-08). Se valida DENTRO de la Lambda además del authorizer."""
from .errors import Forbidden

ROLES = {"operador", "tecnico", "mantenimiento", "supervisor", "admin", "gerencia"}


def claims(event: dict) -> dict:
    return event.get("requestContext", {}).get("authorizer", {}).get("claims", {})


def groups(event: dict) -> set[str]:
    raw = claims(event).get("cognito:groups", "")
    return set(raw.split(",")) if isinstance(raw, str) else set(raw)


def require(event: dict, *allowed: str) -> None:
    if not groups(event) & set(allowed):
        raise Forbidden("El rol no tiene permiso para esta operación")
