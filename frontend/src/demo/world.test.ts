import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/errors";
import { DemoWorld, PROTECTED_TECH } from "./world";

const TECH_07 = { user_id: "u-tec-07", role: "tecnico" as const, name: "Pedro Rojas", technician_id: "TEC-07" };
const MANT = { user_id: "u-mant-01", role: "mantenimiento" as const, name: "Carmen Rojas" };

function code(fn: () => unknown) {
  try {
    fn();
  } catch (e) {
    return e instanceof ApiError ? `${e.status} ${e.code}` : String(e);
  }
  return "ok";
}

describe("DemoWorld: ciclo de vida de GestionIncidente", () => {
  let now: number;
  let w: DemoWorld;
  const advance = (ms: number) => {
    now += ms;
    vi.setSystemTime(now);
    w.tick(now);
  };

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    now = new Date("2026-11-14T15:00:00Z").getTime();
    vi.setSystemTime(now);
    w = new DemoWorld(now);
  });
  afterEach(() => vi.useRealTimers());

  it("arranca con los 100 seeds y el golden path de EX-023", () => {
    expect(w.machines.size).toBe(100);
    expect(w.techs.size).toBe(12);
    const ex = w.machines.get("EX-023")!;
    expect(ex.open_incident_id).toBeTruthy();
    expect(w.incidents.get(ex.open_incident_id!)!.status).toBe("detected");
  });

  it("diagnóstico IA y scoring asignan EX-023 a TEC-07", () => {
    const id = w.machines.get("EX-023")!.open_incident_id!;
    advance(6000);
    const inc = w.incidents.get(id)!;
    expect(inc.ai_diagnosis?.probable_cause).toBeTruthy();
    expect(inc.status).toBe("assigned");
    expect(inc.assigned_technician_id).toBe(PROTECTED_TECH);
    expect(inc.candidates.length).toBe(12); // TRZ-03: se guarda el puntaje de todos los candidatos
  });

  it("ack → resolve → cierre: inventario, máquina y técnico vuelven a su estado", () => {
    const id = w.machines.get("EX-023")!.open_incident_id!;
    advance(6000);
    expect(code(() => w.cmdAck(id, "accept", { ...TECH_07, technician_id: "TEC-02", user_id: "u-tec-02" }))).toBe("403 FORBIDDEN");
    w.cmdAck(id, "accept", TECH_07);
    expect(w.incidents.get(id)!.status).toBe("in_progress");
    expect(code(() => w.cmdAck(id, "accept", TECH_07))).toBe("409 INCIDENT_STATE_INVALID");
    expect(code(() => w.cmdResolve(id, { resolution_notes: "  " }, TECH_07))).toBe("400 VALIDATION_ERROR");

    const tech = w.techs.get("TEC-07")!;
    const stock = w.inventory.find((i) => i.warehouse_id === tech.home_warehouse_id && i.component_id === "CMP-014")!.stock;
    w.cmdResolve(id, { resolution_notes: "Cambio de rodamientos", components_replaced: ["CMP-014"] }, TECH_07);
    expect(w.incidents.get(id)!.status).toBe("resolved");
    advance(5000);

    const inc = w.incidents.get(id)!;
    expect(inc.status).toBe("closed");
    expect(inc.resolution_summary).toContain("Cambio de rodamientos");
    expect(inc.downtime_minutes).not.toBeNull();
    expect(w.machines.get("EX-023")!.open_incident_id).toBeNull();
    expect(w.machines.get("EX-023")!.status).toBe("operational");
    expect(w.inventory.find((i) => i.warehouse_id === tech.home_warehouse_id && i.component_id === "CMP-014")!.stock).toBe(stock - 1);
    expect(tech.current_load).toBe(0);
    expect(w.records.some((r) => r.ref_id === id && r.type === "corrective")).toBe(true);
  });

  it("rechazo: reasigna a otro técnico y no vuelve a elegir al que rechazó", () => {
    const id = w.machines.get("EX-023")!.open_incident_id!;
    advance(6000);
    w.cmdAck(id, "reject", TECH_07, "En otra parada");
    const inc = w.incidents.get(id)!;
    expect(inc.status).toBe("assigned");
    expect(inc.assigned_technician_id).not.toBe("TEC-07");
    expect(inc.rejected).toContain("TEC-07");
  });

  it("timeout de aceptación: escala y reasigna (EsperarAceptacion)", () => {
    w.autopilot = false;
    const free = [...w.machines.values()].find((m) => m.type === "excavator" && !m.open_incident_id && m.home.zone === "sur")!;
    const inc = w.inject("presion", free.machine_id);
    advance(6000);
    const first = inc.assigned_technician_id;
    expect(first).not.toBe(PROTECTED_TECH);
    advance(151_000);
    expect(inc.escalated).toBe(true);
    expect(inc.assigned_technician_id).not.toBe(first);
  });

  it("incidente grupal por zona: padre con hijos, un solo canal de chat (RF-12)", () => {
    const parent = w.inject("grupal_zona", undefined, "sur");
    expect(parent.child_incident_ids.length).toBeGreaterThanOrEqual(2);
    for (const cid of parent.child_incident_ids) {
      const ch = w.incidents.get(cid)!;
      expect(ch.parent_incident_id).toBe(parent.incident_id);
      expect(ch.chat_channel_id).toBe(parent.incident_id);
      expect(code(() => w.cmdAssign(cid, "TEC-02", MANT))).toBe("409 INCIDENT_STATE_INVALID");
    }
    advance(6000);
    expect(parent.ai_diagnosis?.common_cause).toBeTruthy();
    expect(w.incidents.get(parent.child_incident_ids[0]!)!.status).toBe(parent.status);
  });

  it("no permite dos incidentes abiertos sobre la misma máquina", () => {
    expect(code(() => w.inject("degradacion", "EX-023"))).toBe("409 INCIDENT_STATE_INVALID");
  });

  it("la vista pública respeta el schema Incident del OpenAPI (sin campos internos)", () => {
    const allowed = new Set([
      "incident_id", "parent_incident_id", "child_incident_ids", "machine_ids", "zone", "severity", "status", "escalated",
      "is_recurrence", "assigned_technician_id", "technician_score", "ai_diagnosis", "resolution_summary", "detected_at",
      "assigned_at", "accepted_at", "resolved_at", "downtime_minutes", "components_replaced", "cost_usd", "chat_channel_id",
    ]);
    for (const inc of w.incidents.values()) {
      for (const k of Object.keys(w.publicIncident(inc))) expect(allowed.has(k), k).toBe(true);
    }
  });
});
