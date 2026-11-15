/**
 * Analítica del modo demo: misma forma que los `data` que AnalisisDiario (A7) deja en `{p}-insights`
 * y que api-lectura devuelve tal cual (contratos.md §9). Determinista por máquina (hash del ID).
 */
import type { FuelItem, Kpis, MaintenancePlanItem, PartForecast, PartRanking, Precursors, ProductivityItem, Report, Timeline } from "@/api/types";
import { COMPONENT_BY_ID, MODEL_BY_ID, SEED } from "./data";
import { clamp, hash, mulberry32 } from "./rng";
import type { DemoWorld } from "./world";

const DAY = 86400_000;
const today = () => new Date().toISOString().slice(0, 10);
const r1 = (n: number) => Math.round(n * 10) / 10;
const r2 = (n: number) => Math.round(n * 100) / 100;

function machineRand(id: string, salt: string) {
  return mulberry32(hash(`${id}|${salt}`));
}

export function maintenancePlan(w: DemoWorld): MaintenancePlanItem[] {
  const now = today();
  const rows = [...w.machines.values()].map((m) => {
    const next = m.next_maintenance_at ?? now;
    const days = Math.round((new Date(next).getTime() - new Date(now).getTime()) / DAY);
    const p = m.failure_probability ?? 0;
    let flag: MaintenancePlanItem["flag"] = "on_track";
    let reason = `Preventivo por horas de uso (${days >= 0 ? `en ${days} d` : `hace ${-days} d`}).`;
    if (days < 0) {
      flag = "overdue";
      reason = `Vencido hace ${-days} d. Probabilidad de falla ${Math.round(p * 100)}%: priorizar.`;
    } else if (m.health_score >= 88 && p < 0.1 && days <= 7) {
      flag = "unnecessary";
      reason = `Health ${m.health_score}/100 y sin anomalías: se puede postergar y ahorrar la parada.`;
    } else if (p >= 0.35) {
      reason = `Condición degradada (health ${m.health_score}): adelantar el preventivo.`;
    }
    const urgency = (flag === "overdue" ? 2 : 0) + p * 3 - Math.max(days, -30) / 30;
    return { machine_id: m.machine_id, zone: m.home.zone ?? "", next_maintenance_at: next, flag, reason, urgency };
  });
  rows.sort((a, b) => b.urgency - a.urgency);
  return rows.map(({ urgency, ...r }, i) => (void urgency, { ...r, priority: i + 1 }));
}

export function partsRanking(w: DemoWorld): PartRanking[] {
  const since = new Date(Date.now() - 90 * DAY).toISOString().slice(0, 10);
  const used = new Map<string, number>();
  for (const r of w.records) {
    if (r.performed_at < since) continue;
    for (const c of r.components) used.set(c, (used.get(c) ?? 0) + (r.type === "preventive" ? 1 : 2));
  }
  const values = [...used.values()];
  const mean = values.reduce((a, b) => a + b, 0) / Math.max(1, values.length);
  const sd = Math.sqrt(values.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(1, values.length));
  return SEED.catalog
    .map((c) => {
      const units = used.get(c.component_id) ?? 0;
      return { component_id: c.component_id, name: c.name, units_used_90d: units, irregular_consumption: units > mean + 1.5 * sd && units > 3 };
    })
    .sort((a, b) => b.units_used_90d - a.units_used_90d);
}

export function partsForecast(w: DemoWorld, horizon: 7 | 30 | 90 = 30, warehouseId?: string): PartForecast[] {
  const ranking = new Map(partsRanking(w).map((p) => [p.component_id, p.units_used_90d]));
  const planned = maintenancePlan(w).filter((p) => p.flag !== "unnecessary" && new Date(p.next_maintenance_at).getTime() < Date.now() + horizon * DAY);
  return w.inventory
    .filter((i) => !warehouseId || i.warehouse_id === warehouseId)
    .map((i) => {
      const comp = COMPONENT_BY_ID.get(i.component_id);
      const daily = (ranking.get(i.component_id) ?? 0) / 90 / 3; // 3 almacenes
      const plannedHere = ["CMP-001", "CMP-002", "CMP-003"].includes(i.component_id)
        ? planned.filter((p) => w.machines.get(p.machine_id)?.home.zone === i.zone).length
        : 0;
      const demand = r1(daily * horizon + plannedHere);
      const lead = comp?.lead_time_days ?? 7;
      const min = Math.max(1, Math.ceil(daily * lead * 1.5 + plannedHere * 0.5));
      const max = Math.max(min + 2, Math.ceil(min * 2.2 + daily * horizon * 0.5));
      return {
        warehouse_id: i.warehouse_id,
        component_id: i.component_id,
        expected_demand: demand,
        stock: i.stock,
        recommended_min: min,
        recommended_max: max,
        shortage_for_planned_maintenance: i.stock < demand,
      };
    });
}

export function fuel(w: DemoWorld, zone?: string): FuelItem[] {
  const rows = [...w.machines.values()]
    .filter((m) => !zone || m.home.zone === zone)
    .map((m) => {
      const model = MODEL_BY_ID.get(m.model)!;
      const rand = machineRand(m.machine_id, "fuel");
      const anomalous = m.scenario === "combustible";
      const bias = (rand() - 0.5) * 0.18 + (anomalous ? 0.22 : 0) + (rand() < 0.08 ? 0.12 : 0);
      const lph = model.nominal.fuel_rate_lph![0] * (1 + bias);
      const tph = model.payload_t > 0 ? model.payload_t * (model.type === "mining_truck" ? 0.5 : 6) : 25;
      return { m, model, lph, lPerTon: lph / tph, bias, progressive: anomalous || bias > 0.14, rand };
    });
  const byModel = new Map<string, number[]>();
  rows.forEach((r) => byModel.set(r.m.model, [...(byModel.get(r.m.model) ?? []), r.lph]));
  return rows
    .map((r) => {
      const peers = byModel.get(r.m.model)!;
      const peerAvg = peers.reduce((a, b) => a + b, 0) / peers.length;
      const causes: string[] = [];
      if (r.m.scenario === "combustible") causes.push("Inyectores obstruidos", "Filtro de combustible saturado");
      else if (r.bias > 0.12) causes.push("Ralentí prolongado", "Presión de neumáticos baja");
      else if (r.bias > 0.06) causes.push("Estilo de operación agresivo");
      return {
        machine_id: r.m.machine_id,
        zone: r.m.home.zone ?? "",
        lph: r1(r.lph),
        l_per_ton: Math.round(r.lPerTon * 1000) / 1000,
        vs_peers_pct: r1(((r.lph - peerAvg) / peerAvg) * 100),
        vs_own_history_pct: r1(r.bias * 100 * 0.8 + (r.rand() - 0.5) * 3),
        progressive_increase: r.progressive,
        probable_causes: causes,
      };
    })
    .sort((a, b) => b.vs_peers_pct - a.vs_peers_pct);
}

export function productivity(w: DemoWorld, zone?: string): ProductivityItem[] {
  const fuelBy = new Map(fuel(w).map((f) => [f.machine_id, f]));
  const rows = [...w.machines.values()]
    .filter((m) => !zone || m.home.zone === zone)
    .map((m) => {
      const rand = machineRand(m.machine_id, "util");
      const util = clamp(30 + rand() * 68 - (m.open_incident_id ? 15 : 0), 5, 99);
      const f = fuelBy.get(m.machine_id)!;
      const cost = f.lph * 1.15 + 18 + rand() * 25;
      return { m, util: r1(util), cost: r1(cost) };
    });
  const medCost = [...rows].sort((a, b) => a.cost - b.cost)[Math.floor(rows.length / 2)]?.cost ?? 0;
  const under = rows.filter((r) => r.util < 50);
  const over = rows.filter((r) => r.util > 85);
  return rows.map(({ m, util, cost }) => {
    const classification = util < 50 ? "underused" : util > 85 ? "overused" : "normal";
    const highProd = util >= 65;
    const quadrant = `${highProd ? "high" : "low"}_prod_${cost >= medCost ? "high" : "low"}_cost` as ProductivityItem["quadrant"];
    let suggestion: string | null = null;
    if (classification === "overused") {
      const peer = under.find((u) => u.m.type === m.type && u.m.home.zone === m.home.zone) ?? under.find((u) => u.m.type === m.type);
      suggestion = peer ? `Redistribuir carga hacia ${peer.m.machine_id} (${peer.util}% de uso)` : "Programar descanso: riesgo de desgaste acelerado";
    } else if (classification === "underused") {
      const peer = over.find((o) => o.m.type === m.type);
      suggestion = peer ? `Puede absorber turnos de ${peer.m.machine_id} (${peer.util}% de uso)` : "Evaluar reubicación a otra zona";
    }
    return { machine_id: m.machine_id, zone: m.home.zone ?? "", utilization_pct: util, classification, cost_per_hour_usd: cost, quadrant, redistribution_suggestion: suggestion };
  });
}

export function kpis(w: DemoWorld, zone?: string, period: "7d" | "30d" = "7d"): Kpis {
  const since = Date.now() - (period === "7d" ? 7 : 30) * DAY;
  const machines = [...w.machines.values()].filter((m) => !zone || m.home.zone === zone);
  const incidents = [...w.incidents.values()].filter((i) => !i.parent_incident_id && (!zone || i.zone === zone));
  const closed = incidents.filter((i) => i.status === "closed" && new Date(i.detected_at).getTime() >= since);
  const downtime = closed.reduce((a, i) => a + (i.downtime_minutes ?? 0), 0);
  const hours = machines.length * (period === "7d" ? 7 : 30) * 24;
  const util = productivity(w, zone);
  const fuelRows = fuel(w, zone);
  const avgLpt = fuelRows.reduce((a, f) => a + f.l_per_ton, 0) / Math.max(1, fuelRows.length);
  const failures = Math.max(1, closed.length);
  return {
    availability_pct: r1(clamp(100 - (downtime / 60 / Math.max(1, hours)) * 100 - machines.filter((m) => m.status !== "operational").length / Math.max(1, machines.length) * 100 * 0.5, 0, 100)),
    mtbf_hours: r1(hours / failures),
    mttr_hours: r1(downtime / 60 / failures),
    open_incidents: incidents.filter((i) => i.status !== "closed").length,
    machines_at_risk: machines.filter((m) => m.health_score < 70 || m.severity === "high" || m.severity === "critical").length,
    fleet_utilization_pct: r1(util.reduce((a, u) => a + u.utilization_pct, 0) / Math.max(1, util.length)),
    fuel_cost_per_ton_usd: Math.round(avgLpt * 1.15 * 100) / 100,
  };
}

/**
 * Firmas pre-falla (TAREA-12): mismas llaves que el insight `precursors` (GET /analytics/precursors).
 * Demo: para los 3 modelos más comunes de la flota genera 3 firmas deterministas por modelo.
 */
export function precursors(w: DemoWorld): Precursors {
  const count = new Map<string, number>();
  for (const m of w.machines.values()) count.set(m.model, (count.get(m.model) ?? 0) + 1);
  const top = [...count.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 3);
  const variables = ["vibration_mm_s", "temperature_c", "fuel_rate_lph"];
  return {
    precursors: top.map(([model, machines]) => {
      const rand = machineRand(model, "precursors");
      const signatures = variables
        .map((variable, i) => ({
          variable,
          share: Math.max(0.2, r2(0.78 - i * 0.19 - rand() * 0.05)),
          median_lead_time_h: r1(18 + i * 4 + rand() * 5),
          median_z: r1(1.7 - i * 0.3 + rand() * 0.4),
        }))
        .sort((a, b) => b.share - a.share);
      const best = signatures[0];
      const sign = best.median_z >= 0 ? "+" : "";
      return {
        model,
        n_incidents: 6 + Math.floor(rand() * 6) + Math.round(machines / 4),
        signatures,
        headline: `En ${model}, ${Math.round(best.share * 100)} % de las fallas fueron precedidas por ${best.variable} (${sign}${best.median_z.toFixed(1)}σ) ~${Math.round(best.median_lead_time_h)} h antes`,
      };
    }),
  };
}

export function report(w: DemoWorld): Report {
  const k = kpis(w, undefined, "7d");
  const plan = maintenancePlan(w);
  const overdue = plan.filter((p) => p.flag === "overdue").length;
  const unnecessary = plan.filter((p) => p.flag === "unnecessary").length;
  const fuelTop = fuel(w).slice(0, 3).map((f) => `${f.machine_id} (+${f.vs_peers_pct}%)`);
  const low = w.inventory.filter((i) => i.alert === "low_stock").length;
  const at = new Date();
  at.setHours(6, 0, 0, 0);
  return {
    generated_at: at.toISOString(),
    prompt_version: "executive_report@1.1",
    summary_text:
      `Disponibilidad de la flota en ${k.availability_pct}% con MTTR de ${k.mttr_hours} h y MTBF de ${k.mtbf_hours} h en los últimos 7 días. ` +
      `Hay ${k.open_incidents} incidentes abiertos y ${k.machines_at_risk} máquinas en riesgo según el modelo predictivo. ` +
      `${overdue} mantenimientos preventivos están vencidos y ${unnecessary} pueden postergarse sin riesgo, liberando horas de parada. ` +
      `Mayor desvío de combustible frente a sus pares: ${fuelTop.join(", ")}. ` +
      `${low ? `${low} repuestos están bajo el stock mínimo; revisar el pronóstico a 30 días antes de las paradas programadas.` : "El inventario cubre las paradas programadas."}`,
    figures: { ...k, overdue_maintenance: overdue, postponable_maintenance: unnecessary, low_stock_items: low },
  };
}

export function timeline(w: DemoWorld, machineId: string): Timeline {
  const inc = [...w.incidents.values()].filter((i) => i.machine_ids.includes(machineId) && (!i.child_incident_ids.length || i.machine_ids.length === 1));
  const events: Timeline["events"] = [
    ...inc.flatMap((i) => [
      { at: i.detected_at, kind: "anomaly" as const, ref_id: i.incident_id, summary: i.ai_diagnosis?.top_factors.map((f) => `${f.variable} z=${f.z_score}`).join(", ") || "Anomalía detectada" },
      { at: i.resolved_at ?? i.detected_at, kind: "incident" as const, ref_id: i.incident_id, summary: `${i.severity.toUpperCase()} · ${i.ai_diagnosis?.probable_cause ?? "Diagnóstico pendiente"} (${i.status})` },
    ]),
    ...w.records
      .filter((r) => r.machine_id === machineId)
      .map((r) => ({
        at: `${r.performed_at}T12:00:00Z`,
        kind: r.type,
        ref_id: r.ref_id,
        summary: `${r.type === "preventive" ? "Preventivo" : "Correctivo"}: ${r.components.map((c) => COMPONENT_BY_ID.get(c)?.name ?? c).join(", ") || "inspección"}`,
      })),
  ].sort((a, b) => b.at.localeCompare(a.at));
  const closed = inc.filter((i) => i.status === "closed");
  const downtimeH = closed.reduce((a, i) => a + (i.downtime_minutes ?? 0), 0) / 60;
  const window = 90 * 24;
  return {
    events,
    kpis: {
      mtbf_hours: r1(window / Math.max(1, closed.length)),
      mttr_hours: r1(downtimeH / Math.max(1, closed.length)),
      availability_pct: r1(clamp(100 - (downtimeH / window) * 100, 0, 100)),
    },
  };
}
