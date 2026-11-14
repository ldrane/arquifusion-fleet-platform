import type { Aggregate, TelemetryPoint, TelemetryReading } from "@/api/types";
import { MODEL_BY_ID, SCENARIO_BY_KEY } from "./data";
import { clamp, gaussian, hash, mulberry32 } from "./rng";

/** Ventana durante la que una falla progresiva "se ve venir" en la telemetría antes de la detección. */
const RAMP_MS = 6 * 3600_000;

export interface DegradationSource {
  scenario: string;
  detectedAt: number;
}

export interface TelemetryMachine {
  machine_id: string;
  model: string;
  type: TelemetryReading["type"];
  baseHealth: number;
  health: number;
  operating_hours: number;
  location: TelemetryReading["location"];
  status: string;
}

/** Factor 0..1 de cuánto de la anomalía ya está presente en el instante t. */
function rampAt(t: number, d?: DegradationSource | null): number {
  if (!d) return 0;
  const start = d.detectedAt - RAMP_MS;
  return clamp((t - start) / RAMP_MS, 0, 1);
}

function value(m: TelemetryMachine, variable: string, t: number, d: DegradationSource | null, salt = ""): number {
  const model = MODEL_BY_ID.get(m.model);
  const [mean, sd] = model?.nominal[variable] ?? [0, 1];
  const rand = mulberry32(hash(`${m.machine_id}|${variable}|${Math.floor(t / 60000)}${salt}`));
  // Ciclo de turno suave (la carga y el combustible siguen el ritmo de la operación) + ruido gaussiano.
  const cycle = Math.sin((t / 3600_000) * ((2 * Math.PI) / 12) + (hash(m.machine_id) % 7)) * 0.35;
  const z = d ? (SCENARIO_BY_KEY.get(d.scenario)?.vars[variable] ?? 0) * rampAt(t, d) : 0;
  return Math.max(0, mean + sd * (cycle + gaussian(rand) * 0.45 + z));
}

const VARS = ["temperature_c", "vibration_mm_s", "pressure_bar", "fuel_rate_lph"] as const;

function aggregate(m: TelemetryMachine, variable: string, t: number, stepMs: number, d: DegradationSource | null): Aggregate {
  const samples = [0, 0.33, 0.66].map((f, i) => value(m, variable, t + stepMs * f, d, `#${i}`));
  const r = (n: number) => Math.round(n * 100) / 100;
  return { min: r(Math.min(...samples)), avg: r(samples.reduce((a, b) => a + b, 0) / samples.length), max: r(Math.max(...samples)) };
}

function healthAt(m: TelemetryMachine, t: number, d: DegradationSource | null): number {
  const r = rampAt(t, d);
  const rand = mulberry32(hash(`${m.machine_id}|h|${Math.floor(t / 600000)}`));
  return Math.round(clamp(m.baseHealth - (m.baseHealth - m.health) * r + (rand() - 0.5) * 2, 0, 100));
}

/** Serie de GET /v1/machines/{id}/telemetry (buckets de 1 min o 1 h, máx. 720 puntos). */
export function telemetrySeries(
  m: TelemetryMachine,
  fromIso: string,
  toIso: string,
  resolution: "1m" | "1h",
  d: DegradationSource | null,
): TelemetryPoint[] {
  const step = resolution === "1h" ? 3600_000 : 60_000;
  const to = Math.min(new Date(toIso).getTime(), Date.now());
  let from = new Date(fromIso).getTime();
  if (Number.isNaN(from) || Number.isNaN(to) || from >= to) return [];
  from = Math.max(from, to - step * 720);
  const out: TelemetryPoint[] = [];
  for (let t = Math.floor(from / step) * step; t <= to; t += step) {
    out.push({
      bucket_start: new Date(t).toISOString(),
      temperature_c: aggregate(m, "temperature_c", t, step, d),
      vibration_mm_s: aggregate(m, "vibration_mm_s", t, step, d),
      pressure_bar: aggregate(m, "pressure_bar", t, step, d),
      fuel_rate_lph: aggregate(m, "fuel_rate_lph", t, step, d),
      health_score: healthAt(m, t, d),
    });
  }
  return out;
}

/** latest_reading de MachineDetail: misma forma que TelemetryReading (POST /telemetry). */
export function latestReading(m: TelemetryMachine, t: number, d: DegradationSource | null): TelemetryReading {
  const get = (v: string) => Math.round(value(m, v, t, d) * 10) / 10;
  const state = m.status === "silent" || m.status === "stopped" ? "stopped" : m.status === "maintenance" ? "maintenance" : "operating";
  return {
    machine_id: m.machine_id,
    model: m.model,
    type: m.type,
    timestamp: new Date(t).toISOString(),
    location: m.location,
    operating_hours: m.operating_hours,
    temperature_c: get("temperature_c"),
    vibration_mm_s: get("vibration_mm_s"),
    pressure_bar: get("pressure_bar"),
    fuel_rate_lph: get("fuel_rate_lph"),
    load_pct: get("load_pct"),
    speed_kmh: get("speed_kmh"),
    rpm: Math.round(get("rpm")),
    state,
    sim_scenario: d?.scenario ?? null,
  };
}

export { VARS as TELEMETRY_VARS };
