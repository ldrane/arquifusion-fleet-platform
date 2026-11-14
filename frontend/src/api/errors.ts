/** Error estándar de la API: `{ error: {code, message, details}, correlation_id }` (contratos.md §1). */
export type ErrorCode =
  | "VALIDATION_ERROR"
  | "UNAUTHENTICATED"
  | "FORBIDDEN"
  | "NOT_FOUND"
  | "INCIDENT_STATE_INVALID"
  | "DUPLICATE_EVENT"
  | "RATE_LIMITED"
  | "UPSTREAM_UNAVAILABLE"
  | "INTERNAL"
  | "NETWORK";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: ErrorCode,
    message: string,
    public readonly correlationId: string | null = null,
    public readonly details: { field?: string; issue?: string }[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const FRIENDLY: Partial<Record<ErrorCode, string>> = {
  UNAUTHENTICATED: "Tu sesión expiró. Vuelve a iniciar sesión.",
  FORBIDDEN: "Tu rol no tiene permiso para esta acción.",
  NOT_FOUND: "No se encontró el recurso.",
  INCIDENT_STATE_INVALID: "El incidente cambió de estado; refresca y vuelve a intentarlo.",
  DUPLICATE_EVENT: "Esta acción ya se había registrado.",
  RATE_LIMITED: "Demasiadas solicitudes; espera unos segundos.",
  UPSTREAM_UNAVAILABLE: "Un servicio externo no responde; se reintentará.",
  NETWORK: "Sin conexión con la API.",
};

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const base = FRIENDLY[err.code] ?? err.message;
    return err.correlationId ? `${base} (ref. ${err.correlationId.slice(0, 8)})` : base;
  }
  return err instanceof Error ? err.message : String(err);
}
