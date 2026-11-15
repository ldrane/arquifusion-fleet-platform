/**
 * Reglas del chat del incidente en el front, espejo de infra/gcp/firestore.rules (RF-15, contratos.md §5).
 * Si la UI deja escribir a alguien que las reglas rechazan, Firestore descarta el mensaje en silencio
 * (aparece "pendiente" y desaparece). Por eso la UI usa exactamente las mismas condiciones.
 */
import type { Incident, Me } from "@/api/types";
import { can } from "@/auth/permissions";
import { myTechnicianId } from "@/lib/ids";

export type ChatWriteState = "ok" | "closed" | "role" | "not_assigned";

/** create en incidents/{id}/messages: rol tecnico|mantenimiento|supervisor, incidente abierto y,
 *  si es técnico, asignado a él (assigned_technician_id == claim technician_id). */
export function chatWriteState(me: Pick<Me, "role" | "user_id" | "technician_id"> | null | undefined, incident: Incident): ChatWriteState {
  if (incident.status === "closed") return "closed";
  if (!me || !can(me.role, "chatWrite")) return "role";
  if (me.role === "tecnico" && incident.assigned_technician_id !== myTechnicianId(me)) return "not_assigned";
  return "ok";
}

export const CHAT_WRITE_HINT: Record<Exclude<ChatWriteState, "ok">, string> = {
  closed: "Incidente cerrado: el chat queda como registro de solo lectura.",
  role: "Tu rol puede leer el chat, pero no escribir (Security Rules).",
  not_assigned: "Solo el técnico asignado a este incidente puede escribir en su chat.",
};

/**
 * Espera la confirmación del servidor de una escritura de Firestore, sin bloquear el modo offline:
 * - sin conexión: no espera (el SDK la deja en cola en IndexedDB) y reporta un rechazo posterior con `onLateError`;
 * - con conexión: espera hasta `timeoutMs`; un rechazo (p. ej. permission-denied) se propaga para mostrarlo.
 * Antes el front hacía `void addDoc(...)`: un rechazo de las reglas se perdía y el mensaje "desaparecía".
 */
export async function settleWrite(
  write: Promise<unknown>,
  { online, timeoutMs = 8000, onLateError }: { online: boolean; timeoutMs?: number; onLateError?: (e: unknown) => void },
): Promise<"sent" | "queued"> {
  if (!online) {
    write.catch((e) => onLateError?.(e));
    return "queued";
  }
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<"queued">((resolve) => {
    timer = setTimeout(() => resolve("queued"), timeoutMs);
  });
  try {
    const r = await Promise.race([write.then(() => "sent" as const), timeout]);
    if (r === "queued") write.catch((e) => onLateError?.(e));
    return r;
  } finally {
    clearTimeout(timer);
  }
}
