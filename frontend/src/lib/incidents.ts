import type { Incident } from "@/api/types";

/** Un incidente sigue "en curso" mientras no se cierre (mismo criterio que el demo: `status !== "closed"`). */
export function isOpenIncident(i: Incident): boolean {
  return ["detected", "assigned", "in_progress"].includes(i.status);
}

/**
 * Un representante por grupo de correlación (RF-12.1): el incidente padre, o el más antiguo del ciclo
 * si el grafo viene mal formado (dos incidentes que se apuntan mutuamente, visto en producción por una
 * carrera de `correlacion`). Se agrupa por `parent_incident_id` con union-find, así que el resultado no
 * depende del orden y nunca queda vacío por un ciclo.
 *
 * Con datos bien formados equivale a `incidents.filter((i) => !i.parent_incident_id)`.
 */
export function groupRoots(incidents: Incident[]): Incident[] {
  const byId = new Map(incidents.map((i) => [i.incident_id, i]));

  const parent = new Map<string, string>();
  const find = (x: string): string => {
    let root = x;
    while (parent.get(root) !== undefined && parent.get(root) !== root) root = parent.get(root)!;
    for (let n = x; parent.get(n) !== undefined && parent.get(n) !== n; ) {
      const next = parent.get(n)!;
      parent.set(n, root);
      n = next;
    }
    return root;
  };
  const union = (a: string, b: string) => {
    const ra = find(a);
    const rb = find(b);
    if (ra !== rb) parent.set(ra, rb);
  };

  for (const i of incidents) {
    const p = i.parent_incident_id;
    if (p && p !== i.incident_id && byId.has(p)) union(i.incident_id, p);
  }

  const groups = new Map<string, Incident[]>();
  for (const i of incidents) {
    const root = find(i.incident_id);
    const members = groups.get(root);
    if (members) members.push(i);
    else groups.set(root, [i]);
  }

  const out: Incident[] = [];
  for (const members of groups.values()) {
    const root =
      members.find((m) => !m.parent_incident_id) ??
      members.reduce((a, b) => (a.detected_at <= b.detected_at ? a : b));
    out.push(root);
  }
  return out;
}

/**
 * Cola de incidentes abiertos: **un elemento por grupo de correlación** (RF-12.1).
 *
 * Un grupo es un incidente padre más sus `child_incident_ids`; en la cola solo se muestra el padre
 * para no repetir la misma avería una vez por máquina. Si el grupo tiene un ciclo, se toma el
 * detectado más antiguo del ciclo, así la cola nunca queda vacía por un grafo mal formado.
 *
 * Sin ciclos equivale al filtro histórico `status !== "closed" && !parent_incident_id`.
 */
export function openIncidents(incidents: Incident[]): Incident[] {
  return groupRoots(incidents.filter(isOpenIncident));
}
