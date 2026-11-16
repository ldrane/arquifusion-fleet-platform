import type { Incident } from "@/api/types";
import { describe, expect, it } from "vitest";
import { groupRoots, isOpenIncident, openIncidents } from "./incidents";

/** Incidente mínimo: solo lo que usa la cola (id, padre, estado, antigüedad). */
function inc(id: string, over: Partial<Incident> = {}): Incident {
  return {
    incident_id: id,
    parent_incident_id: null,
    child_incident_ids: [],
    machine_ids: [id],
    zone: "norte",
    severity: "high",
    status: "assigned",
    detected_at: "2026-11-15T22:32:35Z",
    ...over,
  } as Incident;
}

describe("openIncidents", () => {
  it("muestra el incidente padre una vez y oculta los hijos", () => {
    const parent = inc("INC-P", { child_incident_ids: ["INC-C1", "INC-C2"] });
    const c1 = inc("INC-C1", { parent_incident_id: "INC-P" });
    const c2 = inc("INC-C2", { parent_incident_id: "INC-P" });
    expect(openIncidents([parent, c1, c2]).map((i) => i.incident_id)).toEqual(["INC-P"]);
  });

  it("excluye los cerrados", () => {
    expect(openIncidents([inc("INC-A", { status: "closed" }), inc("INC-B")])).toHaveLength(1);
    expect(isOpenIncident(inc("INC-A", { status: "closed" }))).toBe(false);
  });

  // Regresión del bug en la nube: `correlacion` enlazó dos incidentes mutuamente (carrera), así que
  // TODOS los abiertos tenían `parent_incident_id` y el filtro `!parent_incident_id` dejaba la cola
  // vacía. La cola debe seguir mostrando el grupo (el más antiguo del ciclo).
  it("no se vacía cuando el grupo tiene un ciclo padre↔hijo", () => {
    const a = inc("INC-A", { parent_incident_id: "INC-B", detected_at: "2026-11-15T22:32:35Z", child_incident_ids: ["INC-B", "INC-C"] });
    const b = inc("INC-B", { parent_incident_id: "INC-A", detected_at: "2026-11-15T23:03:46Z", child_incident_ids: ["INC-A"] });
    const c = inc("INC-C", { parent_incident_id: "INC-A" });
    const queue = openIncidents([a, b, c]);
    expect(queue.map((i) => i.incident_id)).toEqual(["INC-A"]);
  });

  it("un grupo sigue siendo uno solo aunque el ciclo sea de dos y haya muchas máquinas", () => {
    const a = inc("INC-A", { parent_incident_id: "INC-B", detected_at: "2026-11-15T22:00:00Z" });
    const b = inc("INC-B", { parent_incident_id: "INC-A", detected_at: "2026-11-15T22:05:00Z" });
    const kids = Array.from({ length: 27 }, (_, n) => inc(`INC-K${n}`, { parent_incident_id: "INC-A" }));
    expect(openIncidents([a, b, ...kids]).map((i) => i.incident_id)).toEqual(["INC-A"]);
  });

  it("no oculta un hijo abierto cuyo padre ya se cerró", () => {
    const parent = inc("INC-P", { status: "closed" });
    const child = inc("INC-C", { parent_incident_id: "INC-P" });
    expect(openIncidents([parent, child]).map((i) => i.incident_id)).toEqual(["INC-C"]);
  });

  it("mantiene separados los grupos de zonas distintas", () => {
    const norte = inc("INC-N", { zone: "norte", child_incident_ids: ["INC-N1"] });
    const n1 = inc("INC-N1", { zone: "norte", parent_incident_id: "INC-N" });
    const sur = inc("INC-S", { zone: "sur" });
    expect(openIncidents([norte, n1, sur]).map((i) => i.incident_id).sort()).toEqual(["INC-N", "INC-S"]);
  });
});

describe("groupRoots", () => {
  it("agrupa también los cerrados (una fila por grupo en el historial)", () => {
    const parent = inc("INC-P", { status: "closed", child_incident_ids: ["INC-C"] });
    const child = inc("INC-C", { status: "closed", parent_incident_id: "INC-P" });
    const solo = inc("INC-S", { status: "closed" });
    expect(groupRoots([parent, child, solo]).map((i) => i.incident_id).sort()).toEqual(["INC-P", "INC-S"]);
  });

  it("un grupo mixto (padre cerrado, hijo abierto) se resuelve por separado en el historial", () => {
    const parent = inc("INC-P", { status: "closed", child_incident_ids: ["INC-C"] });
    const child = inc("INC-C", { parent_incident_id: "INC-P" });
    // groupRoots sobre todo el conjunto colapsa al padre (una fila por grupo)...
    expect(groupRoots([parent, child]).map((i) => i.incident_id)).toEqual(["INC-P"]);
    // ...por eso el historial agrupa abiertos y cerrados por separado: así el hijo abierto no desaparece.
    const rows = [
      ...openIncidents([parent, child]),
      ...groupRoots([parent, child].filter((i) => i.status === "closed")),
    ];
    expect(rows.map((i) => i.incident_id).sort()).toEqual(["INC-C", "INC-P"]);
  });

  it("openIncidents es groupRoots de los abiertos", () => {
    const items = [inc("INC-P", { status: "closed" }), inc("INC-C"), inc("INC-C2", { parent_incident_id: "INC-C" })];
    expect(openIncidents(items).map((i) => i.incident_id)).toEqual(groupRoots(items.filter(isOpenIncident)).map((i) => i.incident_id));
  });
});
