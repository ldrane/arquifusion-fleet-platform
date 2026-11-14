/** correlation_id de punta a punta (contratos.md §1): uno por acción del usuario. */
export function newCorrelationId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

const CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

/** ULID corto (timestamp + aleatorio) para el formato INC-<ULID> de contratos.md §1. */
export function shortUlid(now = Date.now()): string {
  let t = now;
  let time = "";
  for (let i = 0; i < 6; i++) {
    time = CROCKFORD[t % 32] + time;
    t = Math.floor(t / 32);
  }
  let rand = "";
  for (let i = 0; i < 4; i++) rand += CROCKFORD[Math.floor(Math.random() * 32)];
  return time + rand;
}

/**
 * RESPALDO: user_id de Cognito (u-tec-07) -> technician_id (TEC-07), mismo mapeo que los seeds.
 * La fuente de verdad es el claim `custom:technician_id` que devuelve GET /me (contratos.md §2.1, #8):
 * usa `myTechnicianId(me)`.
 */
export function technicianIdFromUser(userId: string): string | null {
  const m = /^u-tec-(\d+)$/i.exec(userId);
  return m ? `TEC-${m[1].padStart(2, "0")}` : null;
}

/** technician_id del usuario: `me.technician_id` (GET /me) y, solo si falta, el mapeo por user_id. */
export function myTechnicianId(me: { user_id: string; technician_id?: string | null } | null | undefined): string | null {
  if (!me) return null;
  return me.technician_id ?? technicianIdFromUser(me.user_id);
}
