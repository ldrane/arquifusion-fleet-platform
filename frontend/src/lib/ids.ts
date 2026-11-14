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

/** user_id de Cognito (u-tec-07) -> technician_id (TEC-07). Mismo mapeo que los seeds (Technicians.user_id). */
export function technicianIdFromUser(userId: string): string | null {
  const m = /^u-tec-(\d+)$/i.exec(userId);
  return m ? `TEC-${m[1].padStart(2, "0")}` : null;
}
