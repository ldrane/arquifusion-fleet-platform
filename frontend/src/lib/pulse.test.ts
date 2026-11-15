import { describe, expect, it } from "vitest";
import type { Pulse } from "@/api/types";
import { pulseLabel, pulseState } from "./pulse";

const base: Pulse = {
  mode: "live",
  region: "us-east-1",
  last_reading_at: "2026-11-14T12:00:00Z",
  machines_reporting_5m: 97,
  open_incidents: 2,
  model_version: "v3",
  last_report_at: "2026-11-14T06:00:00Z",
  ai: { last_provider: "gemini", degraded: false },
  generated_at: "2026-11-14T12:00:00Z",
};
const NOW = new Date("2026-11-14T12:00:30Z").getTime(); // 30 s después de la última lectura

describe("badge de pulso del sistema (TAREA-14)", () => {
  it("verde LIVE con telemetría fresca (< 60 s)", () => {
    expect(pulseState(base, NOW)).toBe("live");
    expect(pulseLabel(base, "live")).toBe("LIVE · AWS us-east-1 + GCP");
  });

  it("ámbar LIVE sin telemetría reciente", () => {
    expect(pulseState({ ...base, last_reading_at: "2026-11-14T11:50:00Z" }, NOW)).toBe("stale");
    expect(pulseState({ ...base, last_reading_at: null }, NOW)).toBe("stale");
    expect(pulseLabel(base, "stale")).toBe("LIVE · sin telemetría reciente");
  });

  it("gris DEMO cuando el front corre en el navegador", () => {
    expect(pulseState({ ...base, mode: "demo" }, NOW)).toBe("demo");
    expect(pulseLabel({ ...base, mode: "demo" }, "demo")).toBe("DEMO");
  });
});
