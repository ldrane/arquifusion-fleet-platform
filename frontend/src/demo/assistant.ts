/**
 * Asistente del modo demo. Imita el tool-calling de ia-gemini (RF-14): detecta la intención, "llama"
 * a una herramienta sobre los datos reales del mundo y redacta la respuesta. Nunca SQL libre.
 */
import type { AssistantAnswer, Me } from "@/api/types";
import { SEVERITY_LABEL, STATUS_LABEL } from "@/lib/format";
import { fuel, kpis, maintenancePlan } from "./analytics";
import { ZONES } from "./data";
import type { DemoWorld } from "./world";

const norm = (s: string) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

export function answer(w: DemoWorld, me: Me, message: string, sessionId?: string): AssistantAnswer {
  const q = norm(message);
  const zone = ZONES.find((z) => q.includes(z)) ?? me.zone ?? undefined;
  const zoneTxt = zone ? ` en la zona ${zone}` : "";
  const machineId = /\b([a-z]{2})-?(\d{3,4})\b/i.exec(message);
  const tools: string[] = [];
  let text: string;

  if (machineId) {
    const id = `${machineId[1]!.toUpperCase()}-${machineId[2]}`;
    const m = w.machines.get(id);
    tools.push("get_machine_detail");
    if (!m) text = `No encontré la máquina ${id} en la flota.`;
    else {
      const inc = m.open_incident_id ? w.incidents.get(m.open_incident_id) : undefined;
      text =
        `${id} (${m.model}, zona ${m.home.zone}) está ${STATUS_LABEL[m.status].toLowerCase()} con health ${m.health_score}/100, ` +
        `probabilidad de falla ${Math.round((m.failure_probability ?? 0) * 100)}% y RUL estimado de ${m.rul_hours} h.` +
        (inc ? ` Tiene abierto ${inc.incident_id} (${SEVERITY_LABEL[inc.severity]}): ${inc.ai_diagnosis?.probable_cause ?? "diagnóstico en curso"}.` : " No tiene incidentes abiertos.") +
        (m.top_factors.length ? ` Variables que explican la alerta: ${m.top_factors.map((f) => `${f.variable} (z=${f.z_score})`).join(", ")}.` : "");
    }
  } else if (/(riesgo|falla|peligro|criti)/.test(q)) {
    tools.push("get_machines_at_risk");
    const risk = [...w.machines.values()]
      .filter((m) => (!zone || m.home.zone === zone) && (m.failure_probability ?? 0) >= 0.25)
      .sort((a, b) => (b.failure_probability ?? 0) - (a.failure_probability ?? 0))
      .slice(0, 5);
    text = risk.length
      ? `Máquinas en riesgo${zoneTxt}: ${risk.map((m) => `${m.machine_id} (${Math.round((m.failure_probability ?? 0) * 100)}%, health ${m.health_score})`).join(", ")}. Recomiendo priorizar las de mayor probabilidad en el plan de mantenimiento.`
      : `No hay máquinas con probabilidad de falla relevante${zoneTxt}.`;
  } else if (/(stock|repuesto|inventario|pieza)/.test(q)) {
    tools.push("get_inventory_alerts");
    const low = w.inventory.filter((i) => i.alert === "low_stock" && (!zone || i.zone === zone));
    text = low.length
      ? `Repuestos bajo el mínimo${zoneTxt}: ${low.slice(0, 6).map((i) => `${i.name} en ${i.warehouse_id} (${i.stock}/${i.stock_min})`).join("; ")}.`
      : `No hay repuestos bajo el stock mínimo${zoneTxt}.`;
  } else if (/(tecnico|disponible|despacho)/.test(q)) {
    tools.push("get_technicians");
    const techs = [...w.techs.values()].filter((t) => !zone || t.zone === zone);
    const free = techs.filter((t) => t.available);
    text = `${free.length} de ${techs.length} técnicos disponibles${zoneTxt}: ${free.map((t) => `${t.name} (${t.specialties.join("/")})`).join(", ") || "ninguno"}.`;
  } else if (/(combustible|consumo|diesel)/.test(q)) {
    tools.push("get_fuel_analytics");
    const top = fuel(w, zone).slice(0, 4);
    text = `Mayor consumo frente a sus pares${zoneTxt}: ${top.map((f) => `${f.machine_id} +${f.vs_peers_pct}%${f.probable_causes.length ? ` (${f.probable_causes[0]})` : ""}`).join(", ")}.`;
  } else if (/(mantenimiento|preventivo|vencid)/.test(q)) {
    tools.push("get_maintenance_plan");
    const plan = maintenancePlan(w).filter((p) => !zone || p.zone === zone);
    const overdue = plan.filter((p) => p.flag === "overdue");
    text = `${overdue.length} preventivos vencidos${zoneTxt}. Los más urgentes: ${plan.slice(0, 4).map((p) => `${p.machine_id} (${p.reason})`).join(" ")}`;
  } else if (/(incidente|abierto|alerta)/.test(q)) {
    tools.push("list_open_incidents");
    const open = [...w.incidents.values()].filter((i) => i.status !== "closed" && !i.parent_incident_id && (!zone || i.zone === zone));
    text = open.length
      ? `Hay ${open.length} incidentes abiertos${zoneTxt}: ${open.map((i) => `${i.incident_id} ${SEVERITY_LABEL[i.severity]} en ${i.machine_ids.join("/")} (${i.status})`).join("; ")}.`
      : `No hay incidentes abiertos${zoneTxt}.`;
  } else {
    tools.push("get_fleet_kpis");
    const k = kpis(w, zone);
    text =
      `Resumen${zoneTxt}: disponibilidad ${k.availability_pct}%, ${k.open_incidents} incidentes abiertos, ${k.machines_at_risk} máquinas en riesgo, ` +
      `MTTR ${k.mttr_hours} h y utilización ${k.fleet_utilization_pct}%. Puedes preguntarme por riesgo, repuestos, técnicos, combustible, mantenimiento o una máquina (ej. EX-023).`;
  }
  return { answer: text, session_id: sessionId ?? `S-${Date.now().toString(36)}`, tools_used: tools, degraded: false };
}
