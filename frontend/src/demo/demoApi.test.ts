import { describe, expect, it } from "vitest";
import { fetchAll } from "@/api/client";
import { ApiError } from "@/api/errors";
import type { Me } from "@/api/types";
import { navFor } from "@/auth/permissions";
import { scoreTechnicians } from "@/lib/scoring";
import { DemoApi } from "./demoApi";
import { DemoWorld } from "./world";

const world = new DemoWorld();
let me: Me | null = null;
const api = new DemoApi(world, () => me);
const as = (user_id: string, role: Me["role"], zone: string | null) => (me = { user_id, email: null, role, zone });

async function status(p: Promise<unknown>) {
  try {
    await p;
    return 200;
  } catch (e) {
    return e instanceof ApiError ? e.status : 500;
  }
}

describe("DemoApi aplica las mismas reglas que api-lectura / api-comandos", () => {
  it("401 sin sesión", async () => {
    me = null;
    expect(await status(api.listMachines())).toBe(401);
  });

  it("RBAC por rol (x-roles del OpenAPI)", async () => {
    as("u-op-01", "operador", "norte");
    expect(await status(api.listInventory())).toBe(403);
    expect(await status(api.getTelemetry("EX-023", "2026-11-14T00:00:00Z", "2026-11-14T01:00:00Z"))).toBe(403);
    as("u-ger-01", "gerencia", null);
    expect(await status(api.ack("INC-X", "accept"))).toBe(403);
    expect(await status(api.kpis())).toBe(200);
    as("u-mant-01", "mantenimiento", null);
    expect(await status(api.partsForecast({ horizon_days: 30 }))).toBe(200);
    expect(await status(api.fuel())).toBe(403);
  });

  it("filtro por zona del usuario y 403 si pide otra zona", async () => {
    as("u-op-01", "operador", "norte");
    const ms = await fetchAll((c) => api.listMachines({}, 20, c));
    expect(ms.length).toBeGreaterThan(0);
    expect(ms.every((m) => m.location.zone === "norte")).toBe(true);
    expect(await status(api.listMachines({ zone: "sur" }))).toBe(403);
  });

  it("paginación por cursor recorre las 100 máquinas sin repetir", async () => {
    as("u-adm-01", "admin", null);
    const first = await api.listMachines({}, 30);
    expect(first.data).toHaveLength(30);
    expect(first.next_cursor).toBeTruthy();
    const all = await fetchAll((c) => api.listMachines({}, 30, c));
    expect(new Set(all.map((m) => m.machine_id)).size).toBe(100);
  });

  it("telemetría valida el rango (400 VALIDATION_ERROR)", async () => {
    as("u-adm-01", "admin", null);
    expect(await status(api.getTelemetry("EX-023", "2026-11-14T02:00:00Z", "2026-11-14T01:00:00Z"))).toBe(400);
  });

  it("simStart (TAREA-08) enciende el simulador y respeta el RBAC", async () => {
    as("u-adm-01", "admin", null);
    const state = await api.simStart({ scenario: "falla_subita", machines: ["CM-004"], duration_min: 20 });
    expect(state.enabled).toBe(true);
    expect(state.scenario).toBe("falla_subita");
    expect(state.requested_by).toBe("u-adm-01");
    expect(await api.simState()).toMatchObject({ enabled: true });
    expect((await api.simStop()).enabled).toBe(false);
    as("u-op-01", "operador", "norte");
    expect(await status(api.simStart({ scenario: "falla_subita" }))).toBe(403);
  });

  it("precursors (TAREA-12) devuelve firmas y respeta el RBAC", async () => {
    as("u-adm-01", "admin", null);
    const { precursors } = await api.precursors();
    expect(precursors.length).toBeGreaterThan(0);
    expect(precursors.length).toBeLessThanOrEqual(3);
    for (const g of precursors) {
      expect(g.n_incidents).toBeGreaterThanOrEqual(3);
      expect(g.signatures.length).toBeGreaterThan(0);
      expect(g.headline).toContain(g.model);
    }
    as("u-op-01", "operador", "norte");
    expect(await status(api.precursors())).toBe(403);
  });

  it("pulse (TAREA-14) responde mode demo y lo ve cualquier rol", async () => {
    as("u-op-01", "operador", "norte");
    const p = await api.pulse();
    expect(p.mode).toBe("demo");
    expect(p.machines_reporting_5m).toBeGreaterThan(0);
    expect(p.open_incidents).toBeGreaterThan(0);
    expect(p.model_version).toBe("v3");
    expect(p.ai.last_provider).toBe("gemini");
    expect(p.generated_at).toBeTruthy();
  });
});

describe("navegación y scoring", () => {
  it("cada rol ve solo sus vistas", () => {
    expect(navFor("operador").map((n) => n.path)).toEqual(["/", "/salud", "/incidentes"]);
    expect(navFor("tecnico").map((n) => n.path)).toContain("/despacho");
    expect(navFor("tecnico").map((n) => n.path)).not.toContain("/inventario");
    expect(navFor("gerencia").map((n) => n.path)).toContain("/eficiencia");
    expect(navFor("admin")).toHaveLength(7);
  });

  it("a igual distancia gana el técnico con la especialidad requerida", () => {
    const loc = { lat: -11.95, lon: -76.4 };
    const base = { location: loc, available: true, shift: "day" as const, current_load: 0 };
    const ranked = scoreTechnicians(
      [
        { ...base, technician_id: "A", name: "A", specialties: ["electrica"] },
        { ...base, technician_id: "B", name: "B", specialties: ["hidraulica"] },
      ],
      { location: loc, severity: "high", specialty: "hidraulica" },
    );
    expect(ranked[0]!.technician_id).toBe("B");
  });
});
