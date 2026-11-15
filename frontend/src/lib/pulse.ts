import type { Pulse } from "@/api/types";

/**
 * Estado del badge de pulso del sistema (TAREA-14), puro para poder testearlo.
 * - `live`: AWS real y telemetría fresca (< 60 s) → verde.
 * - `stale`: AWS real pero sin lectura reciente (o sin ninguna) → ámbar.
 * - `demo`: el front corre con datos simulados en el navegador → gris.
 */
export type PulseState = "live" | "stale" | "demo";

export const PULSE_FRESH_MS = 60_000;

export function pulseState(p: Pulse, now = Date.now()): PulseState {
  if (p.mode === "demo") return "demo";
  const fresh = !!p.last_reading_at && now - new Date(p.last_reading_at).getTime() < PULSE_FRESH_MS;
  return fresh ? "live" : "stale";
}

export function pulseLabel(p: Pulse, state: PulseState): string {
  if (state === "demo") return "DEMO";
  if (state === "stale") return "LIVE · sin telemetría reciente";
  return `LIVE · AWS ${p.region ?? "us-east-1"} + GCP`;
}
