"""Códigos de error del contrato (contratos.md §1)."""


class ApiError(Exception):
    status = 500
    code = "INTERNAL"

    def __init__(self, message: str, details: list | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or []


class ValidationError(ApiError):
    status, code = 400, "VALIDATION_ERROR"


class Unauthenticated(ApiError):
    status, code = 401, "UNAUTHENTICATED"


class Forbidden(ApiError):
    status, code = 403, "FORBIDDEN"


class NotFound(ApiError):
    status, code = 404, "NOT_FOUND"


class IncidentStateInvalid(ApiError):
    status, code = 409, "INCIDENT_STATE_INVALID"


class DuplicateEvent(ApiError):
    status, code = 409, "DUPLICATE_EVENT"


class UpstreamUnavailable(ApiError):
    status, code = 503, "UPSTREAM_UNAVAILABLE"
