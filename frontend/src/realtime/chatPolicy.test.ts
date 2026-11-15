import { describe, expect, it } from "vitest";
import type { Incident } from "@/api/types";
import { chatWriteState, settleWrite } from "./chatPolicy";

const inc = (over: Partial<Incident> = {}) => ({ status: "in_progress", assigned_technician_id: "TEC-07", ...over }) as Incident;

describe("chatWriteState (espejo de firestore.rules, RF-15)", () => {
  it("técnico asignado, operador, mantenimiento y supervisor escriben", () => {
    expect(chatWriteState({ user_id: "u-tec-07", role: "tecnico", technician_id: "TEC-07" }, inc())).toBe("ok");
    expect(chatWriteState({ user_id: "u-op-01", role: "operador" }, inc())).toBe("ok");
    expect(chatWriteState({ user_id: "u-mant-01", role: "mantenimiento" }, inc())).toBe("ok");
    expect(chatWriteState({ user_id: "u-sup-01", role: "supervisor" }, inc())).toBe("ok");
  });
  it("operador con el incidente cerrado queda en solo lectura", () => {
    expect(chatWriteState({ user_id: "u-op-01", role: "operador" }, inc({ status: "closed" }))).toBe("closed");
  });
  it("técnico no asignado no escribe (antes la UI lo permitía y las reglas lo descartaban)", () => {
    expect(chatWriteState({ user_id: "u-tec-02", role: "tecnico", technician_id: "TEC-02" }, inc())).toBe("not_assigned");
    expect(chatWriteState({ user_id: "u-tec-07", role: "tecnico" }, inc())).toBe("ok"); // technician_id derivado del user_id
  });
  it("admin y gerencia solo leen; cerrado es solo lectura", () => {
    for (const role of ["admin", "gerencia"] as const) expect(chatWriteState({ user_id: "x", role }, inc())).toBe("role");
    expect(chatWriteState({ user_id: "u-mant-01", role: "mantenimiento" }, inc({ status: "closed" }))).toBe("closed");
    expect(chatWriteState(null, inc())).toBe("role");
  });
});

describe("settleWrite", () => {
  it("con red propaga el rechazo de las reglas", async () => {
    const denied = Object.assign(new Error("Missing or insufficient permissions."), { code: "permission-denied" });
    await expect(settleWrite(Promise.reject(denied), { online: true })).rejects.toBe(denied);
  });
  it("con red confirma el envío", async () => {
    await expect(settleWrite(Promise.resolve(), { online: true })).resolves.toBe("sent");
  });
  it("sin red no espera y reporta el rechazo tardío", async () => {
    let late: unknown = null;
    let reject!: (e: unknown) => void;
    const write = new Promise((_, r) => (reject = r));
    await expect(settleWrite(write, { online: false, onLateError: (e) => (late = e) })).resolves.toBe("queued");
    reject("boom");
    await new Promise((r) => setTimeout(r, 0));
    expect(late).toBe("boom");
  });
  it("con red lenta deja el mensaje en cola tras el timeout", async () => {
    await expect(settleWrite(new Promise(() => {}), { online: true, timeoutMs: 5 })).resolves.toBe("queued");
  });
});
