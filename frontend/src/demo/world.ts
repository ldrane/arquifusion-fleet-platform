/**
 * Mundo simulado del modo demo. Reproduce, en el navegador, lo que harían los servicios reales:
 *   procesar (A)        -> anomalías sobre la flota de los seeds
 *   GestionIncidente (B) -> diagnóstico IA, scoring, asignación, espera de ack (con escalamiento),
 *                          resolución, resumen IA, cierre, descuento de inventario y MaintenanceRecord
 *   replicar (C)        -> eventos de cambio a los que se suscribe la UI (como onSnapshot de Firestore)
 * Las vistas no saben que es una simulación: hablan con FleetApi y RealtimeSource.
 */
import { ApiError } from "@/api/errors";
import type {
  AiDiagnosis,
  ChatMessage,
  Factor,
  Incident,
  InventoryItem,
  Location,
  MachineDetail,
  Role,
  Severity,
  Specialty,
  Technician,
} from "@/api/types";
import { etaMinutes } from "@/lib/geo";
import { newCorrelationId, shortUlid } from "@/lib/ids";
import { type Candidate, scoreTechnicians } from "@/lib/scoring";
import { COMPONENT_BY_ID, GROUP_CAUSE, MODEL_BY_ID, SCENARIO_BY_KEY, SCENARIOS, SEED, type Scenario, ZONES } from "./data";
import { clamp, gaussian, hash, mulberry32, pick } from "./rng";

// ------------------------------------------------------------------ tiempos de la simulación (ms)
const T = {
  tick: 2500,
  ai: 2500, // ia-gemini diagnose
  assign: 5000, // scoring + asignación
  ackTimeout: 150_000, // EsperarAceptacion: escalamiento
  ackTimeoutProtected: 15 * 60_000, // el técnico demo (TEC-07) tiene más margen para el pitch
  autoAck: 18_000,
  autoResolve: 70_000,
  close: 4000, // resumen IA + cierre
  spawnMin: 40_000,
  spawnMax: 80_000,
};
const MAX_OPEN = 8;

export type Topic = "machines" | "incidents" | "technicians" | "inventory" | "messages" | "notifications";

export interface Notification {
  id: string;
  at: string;
  kind:
    | "incident.detected"
    | "incident.assigned"
    | "incident.escalated"
    | "incident.accepted"
    | "incident.closed"
    | "parts.shortage"
    | "model.trained"
    | "machine.silent";
  severity: Severity;
  title: string;
  body: string;
  incident_id?: string;
  machine_id?: string;
  zone?: string | null;
  technician_id?: string | null;
}

export interface Actor {
  user_id: string;
  role: Role;
  name: string;
  technician_id?: string | null;
}

export interface MachineState extends MachineDetail {
  home: Location;
  baseHealth: number;
  scenario: string | null;
  silentSince?: number;
}

export interface TechState extends Technician {
  user_id: string;
  zone: string;
  home: Location;
  home_warehouse_id: string;
  target: Location | null;
}

export interface IncidentState extends Incident {
  scenario: string;
  specialty: Specialty;
  candidates: Candidate[];
  rejected: string[];
  aiAt: number;
  assignAt: number;
  ackDeadline: number;
  autoAckAt: number;
  autoResolveAt: number;
  closeAt: number;
}

export interface MaintenanceRecord {
  machine_id: string;
  performed_at: string;
  type: "preventive" | "corrective";
  components: string[];
  cost_usd: number;
  ref_id: string;
}

export const PROTECTED_TECH = "TEC-07";
const SYSTEM: Actor = { user_id: "gestion-incidente", role: "supervisor", name: "GestionIncidente" };
const iso = (t: number) => new Date(t).toISOString();
const OPEN = (i: Incident) => i.status !== "closed";

export class DemoWorld {
  machines = new Map<string, MachineState>();
  techs = new Map<string, TechState>();
  inventory: (InventoryItem & { zone: string })[] = [];
  incidents = new Map<string, IncidentState>();
  messages = new Map<string, ChatMessage[]>();
  records: MaintenanceRecord[] = [];
  notifications: Notification[] = [];
  autopilot = true;
  events = 0; // lecturas "procesadas" (para el indicador de eventos/min)

  private listeners = new Set<(topics: Set<Topic>) => void>();
  private dirty = new Set<Topic>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private nextSpawnAt = 0;
  private rand = mulberry32(27);
  private replies: { at: number; incidentId: string; actor: Actor; text: string }[] = [];

  constructor(now = Date.now()) {
    this.seedState(now);
    this.seedHistory(now);
    this.seedOpen(now);
    this.nextSpawnAt = now + 30_000;
    this.dirty.clear();
  }

  // ---------------------------------------------------------------- suscripción (≈ onSnapshot)
  subscribe(fn: (topics: Set<Topic>) => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  private touch(...topics: Topic[]) {
    topics.forEach((t) => this.dirty.add(t));
  }

  private flush() {
    if (!this.dirty.size) return;
    const topics = new Set(this.dirty);
    this.dirty.clear();
    this.listeners.forEach((fn) => fn(topics));
  }

  start() {
    if (this.timer) return;
    this.timer = setInterval(() => this.tick(Date.now()), T.tick);
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  // ---------------------------------------------------------------- estado inicial desde los seeds
  private seedState(now: number) {
    for (const s of SEED.machines) {
      const m: MachineState = {
        machine_id: s.machine_id,
        model: s.model,
        type: s.type,
        location: { ...s.location },
        status: "operational",
        severity: "info",
        health_score: s.health_score,
        last_seen_at: iso(now - Math.floor(this.rand() * 25_000)),
        failure_probability: 0,
        rul_hours: 0,
        operating_hours: s.operating_hours,
        last_maintenance_at: s.last_maintenance_at,
        next_maintenance_at: s.next_maintenance_at,
        open_incident_id: null,
        top_factors: [],
        model_version: "v3",
        home: { ...s.home_location },
        baseHealth: s.health_score,
        scenario: null,
      };
      this.refreshRisk(m);
      this.machines.set(m.machine_id, m);
    }
    for (const t of SEED.technicians) {
      this.techs.set(t.technician_id, {
        technician_id: t.technician_id,
        name: t.name,
        specialties: t.specialties,
        location: { ...t.location },
        available: t.available,
        shift: t.shift,
        current_load: t.current_load,
        user_id: t.user_id,
        zone: t.zone,
        home: { ...t.location },
        home_warehouse_id: t.home_warehouse_id,
        target: null,
      });
    }
    this.inventory = SEED.inventory.map((i) => ({
      warehouse_id: i.warehouse_id,
      component_id: i.component_id,
      name: i.name,
      stock: i.stock,
      stock_min: i.stock_min,
      stock_max: i.stock_max,
      alert: i.alert,
      zone: i.zone,
    }));
  }

  /** Probabilidad de falla y RUL derivados del health score (lo que A expondría en MachineDetail). */
  private refreshRisk(m: MachineState) {
    const h = m.health_score;
    m.failure_probability = Math.round(clamp((100 - h) / 100 * 1.15 - 0.06, 0.01, 0.97) * 100) / 100;
    m.rul_hours = Math.round((h / 100) ** 2 * 900);
  }

  /** 75 días de historia: incidentes cerrados y mantenimientos (alimentan historial, KPIs y analítica). */
  private seedHistory(now: number) {
    const rand = mulberry32(2027);
    const machines = [...this.machines.values()];
    for (const m of machines) {
      this.records.push({
        machine_id: m.machine_id,
        performed_at: m.last_maintenance_at!,
        type: "preventive",
        components: ["CMP-001", "CMP-002", "CMP-003"],
        cost_usd: 203,
        ref_id: `PM-${m.machine_id}-${m.last_maintenance_at}`,
      });
    }
    const seen = new Set<string>();
    for (let i = 0; i < 38; i++) {
      const m = pick(rand, machines);
      const sc = this.scenarioFor(m, rand);
      const detected = now - (2 + rand() * 73) * 86400_000;
      const assigned = detected + (3 + rand() * 9) * 60_000;
      const accepted = assigned + (2 + rand() * 12) * 60_000;
      const resolved = accepted + (35 + rand() * 260) * 60_000;
      const techs = scoreTechnicians([...this.techs.values()], { location: m.location, severity: sc.severity, specialty: sc.specialty });
      const tech = techs[Math.floor(rand() * Math.min(3, techs.length))]!;
      const comps = this.partsFor(m.model, sc.specialty, rand);
      const cost = comps.reduce((a, c) => a + (COMPONENT_BY_ID.get(c)?.cost_usd ?? 0), 0) + Math.round(150 + rand() * 600);
      const id = `INC-${shortUlid(detected)}`;
      const inc: IncidentState = {
        ...this.blankIncident(id, m, sc, detected),
        status: "closed",
        is_recurrence: seen.has(m.machine_id),
        assigned_technician_id: tech.technician_id,
        technician_score: tech.score,
        ai_diagnosis: this.diagnosis(sc, m, 0.62 + rand() * 0.3),
        resolution_summary: sc.summary,
        assigned_at: iso(assigned),
        accepted_at: iso(accepted),
        resolved_at: iso(resolved),
        downtime_minutes: Math.round((resolved - detected) / 60000),
        components_replaced: comps,
        cost_usd: cost,
        chat_channel_id: id,
      };
      seen.add(m.machine_id);
      this.incidents.set(id, inc);
      this.records.push({ machine_id: m.machine_id, performed_at: iso(resolved).slice(0, 10), type: "corrective", components: comps, cost_usd: cost, ref_id: id });
      this.messages.set(id, [
        this.msg(SYSTEM, `Anomalía detectada: ${sc.label}.`, detected),
        this.msg({ user_id: tech.technician_id, role: "tecnico", name: tech.name }, "Recibido, voy en camino.", accepted),
        this.msg({ user_id: tech.technician_id, role: "tecnico", name: tech.name }, sc.summary, resolved - 60_000),
      ]);
    }
  }

  /** Incidentes abiertos al arrancar: cada uno en una etapa distinta del flujo (golden path visible). */
  private seedOpen(now: number) {
    const byId = (id: string) => this.machines.get(id)!;
    const inZone = (zone: string, type?: string) =>
      [...this.machines.values()].filter((m) => m.home.zone === zone && (!type || m.type === type) && !m.open_incident_id);

    // Norte: un camión ya en atención con TEC-01 (así TEC-07 queda como mejor candidato para EX-023)
    const truckN = inZone("norte", "mining_truck")[0]!;
    const a = this.detect([truckN.machine_id], "neumaticos", now - 38 * 60_000);
    this.diagnose(a, now - 37 * 60_000);
    this.assignTo(a, "TEC-01", now - 35 * 60_000, SYSTEM);
    this.accept(a, now - 31 * 60_000);
    a.autoResolveAt = now + 4 * 60_000; // sigue en atención durante la demo (no se cierra en el primer tick)

    // Sur: excavadora con pico de presión, asignada y esperando el ack del técnico
    const exS = inZone("sur", "excavator")[0]!;
    const b = this.detect([exS.machine_id], "presion", now - 4 * 60_000);
    this.diagnose(b, now - 4 * 60_000 + T.ai);
    this.assignBest(b, now - 3 * 60_000);
    b.autoAckAt = now + 25_000;

    // Este: perforadora con consumo anómalo, en atención
    const drillE = inZone("este", "drill")[0]!;
    const c = this.detect([drillE.machine_id], "combustible", now - 70 * 60_000);
    this.diagnose(c, now - 69 * 60_000);
    this.assignBest(c, now - 66 * 60_000);
    this.accept(c, now - 60 * 60_000);
    c.autoResolveAt = now + 60_000;

    // Oeste: incidente grupal (RF-12), recién detectado: se asigna en segundos
    const group = inZone("oeste").filter((m) => m.type !== "drill").slice(0, 3).map((m) => m.machine_id);
    this.detect(group, "combustible", now - 20_000, true);

    // Golden path: EX-023 (contratos.md) con degradación (high, motor). Se asignará a TEC-07 (usuario demo u-tec-07).
    this.detect(["EX-023"], "degradacion", now - 6_000);

    // Pre-alertas sin incidente (Salud Predictiva) y una máquina sin señal (heartbeat, OBS-09)
    for (const [i, m] of inZone("sur").slice(2, 5).concat(inZone("este").slice(1, 2)).entries()) {
      m.health_score = [58, 63, 66, 61][i]!;
      m.severity = i === 0 ? "medium" : "low";
      m.top_factors = [{ variable: i % 2 ? "vibration_mm_s" : "temperature_c", z_score: 2.1 + i * 0.2, direction: "high" }];
      this.refreshRisk(m);
    }
    const silent = inZone("este", "loader")[0];
    if (silent) {
      silent.status = "silent";
      silent.silentSince = now - 9 * 60_000;
      silent.last_seen_at = iso(now - 9 * 60_000);
    }
    void byId;
  }

  // ---------------------------------------------------------------- helpers de dominio
  private scenarioFor(m: { type: string }, rand = this.rand): Scenario {
    const ok = SCENARIOS.filter((s) => !s.types || s.types.includes(m.type as never));
    return pick(rand, ok);
  }

  private partsFor(model: string, specialty: Specialty, rand = this.rand): string[] {
    const compatible = SEED.catalog.filter((c) => c.specialty === specialty && c.compatible_models.includes(model));
    if (!compatible.length) return [];
    const n = 1 + Math.floor(rand() * Math.min(2, compatible.length));
    const out = new Set<string>();
    while (out.size < n) out.add(pick(rand, compatible).component_id);
    return [...out];
  }

  private factors(sc: Scenario): Factor[] {
    return Object.entries(sc.vars)
      .map(([variable, z]) => ({ variable, z_score: Math.round(Math.abs(z) * 10) / 10, direction: (z >= 0 ? "high" : "low") as Factor["direction"] }))
      .sort((a, b) => b.z_score - a.z_score)
      .slice(0, 3);
  }

  private diagnosis(sc: Scenario, m: { model: string }, confidence: number, common?: string | null): AiDiagnosis {
    const parts = this.partsFor(m.model, sc.specialty, mulberry32(hash(m.model + sc.key)));
    const names = parts.map((p) => COMPONENT_BY_ID.get(p)?.name).filter(Boolean).join(", ");
    return {
      probable_cause: common ?? sc.cause,
      suggested_action: names ? `${sc.action}. Repuestos sugeridos: ${names}.` : sc.action,
      common_cause: common ?? null,
      top_factors: this.factors(sc),
      confidence: Math.round(confidence * 100) / 100,
      model_version: "gemini-3.8-flash",
      prompt_version: "diagnose@1.3",
      degraded: false,
    };
  }

  private blankIncident(id: string, m: MachineState, sc: Scenario, detected: number): IncidentState {
    return {
      incident_id: id,
      parent_incident_id: null,
      child_incident_ids: [],
      machine_ids: [m.machine_id],
      zone: m.home.zone ?? "norte",
      severity: sc.severity,
      status: "detected",
      escalated: false,
      is_recurrence: false,
      assigned_technician_id: null,
      technician_score: null,
      ai_diagnosis: null,
      resolution_summary: null,
      detected_at: iso(detected),
      assigned_at: null,
      accepted_at: null,
      resolved_at: null,
      downtime_minutes: null,
      components_replaced: [],
      cost_usd: null,
      chat_channel_id: id,
      scenario: sc.key,
      specialty: sc.specialty,
      candidates: [],
      rejected: [],
      aiAt: detected + T.ai,
      assignAt: detected + T.assign,
      ackDeadline: Infinity,
      autoAckAt: Infinity,
      autoResolveAt: Infinity,
      closeAt: Infinity,
    };
  }

  private msg(actor: Actor, text: string, at: number, quick_action: string | null = null): ChatMessage {
    return {
      id: `MSG-${shortUlid(at)}`,
      author_id: actor.user_id,
      role: actor === SYSTEM ? "sistema" : actor.role,
      text,
      quick_action,
      created_at: iso(at),
      correlation_id: newCorrelationId(),
    };
  }

  private post(incidentId: string, actor: Actor, text: string, at: number, quick?: string | null) {
    const list = this.messages.get(incidentId) ?? [];
    list.push(this.msg(actor, text, at, quick ?? null));
    this.messages.set(incidentId, list);
    this.touch("messages");
  }

  private notify(n: Omit<Notification, "id">) {
    this.notifications.unshift({ ...n, id: `N-${shortUlid()}-${this.notifications.length}` });
    this.notifications = this.notifications.slice(0, 60);
    this.touch("notifications");
  }

  private techName(id: string | null) {
    return id ? (this.techs.get(id)?.name ?? id) : "—";
  }

  private applyToMachines(inc: IncidentState, fn: (m: MachineState) => void) {
    inc.machine_ids.forEach((id) => {
      const m = this.machines.get(id);
      if (m) fn(m);
    });
    this.touch("machines");
  }

  private children(inc: IncidentState): IncidentState[] {
    return inc.child_incident_ids.map((id) => this.incidents.get(id)!).filter(Boolean);
  }

  /** Los hijos de un incidente grupal siguen el estado del padre. */
  private syncChildren(inc: IncidentState) {
    for (const ch of this.children(inc)) {
      ch.status = inc.status;
      ch.assigned_technician_id = inc.assigned_technician_id;
      ch.assigned_at = inc.assigned_at;
      ch.accepted_at = inc.accepted_at;
      ch.resolved_at = inc.resolved_at;
      ch.escalated = inc.escalated;
      ch.downtime_minutes = inc.downtime_minutes;
      ch.resolution_summary = inc.resolution_summary;
    }
  }

  // ---------------------------------------------------------------- ciclo de vida (≈ GestionIncidente)
  /** procesar emite AnomalyDetected -> CrearIncidente (condicional: una máquina, un incidente abierto). */
  detect(machineIds: string[], scenarioKey: string, at: number, group = false): IncidentState {
    const sc = SCENARIO_BY_KEY.get(scenarioKey)!;
    const ms = machineIds.map((id) => this.machines.get(id)).filter((m): m is MachineState => !!m && !m.open_incident_id);
    if (!ms.length) throw new ApiError(409, "INCIDENT_STATE_INVALID", "La máquina ya tiene un incidente abierto");
    const severity: Severity = group ? "high" : sc.severity;
    const parent = this.blankIncident(`INC-${shortUlid(at)}`, ms[0]!, sc, at);
    parent.severity = severity;
    parent.machine_ids = ms.map((m) => m.machine_id);
    parent.is_recurrence = [...this.incidents.values()].some((i) => i.status === "closed" && i.machine_ids.includes(ms[0]!.machine_id));
    this.incidents.set(parent.incident_id, parent);

    if (group && ms.length > 1) {
      for (const m of ms) {
        const ch = this.blankIncident(`INC-${shortUlid(at)}${m.machine_id.slice(-2)}`, m, sc, at);
        ch.severity = severity;
        ch.parent_incident_id = parent.incident_id;
        ch.chat_channel_id = parent.incident_id;
        ch.aiAt = ch.assignAt = Infinity; // los gestiona el padre
        parent.child_incident_ids.push(ch.incident_id);
        this.incidents.set(ch.incident_id, ch);
      }
    }

    const health = { critical: 28, high: 46, medium: 63, low: 74, info: 85 }[severity];
    for (const m of ms) {
      m.open_incident_id = parent.child_incident_ids.find((cid) => this.incidents.get(cid)!.machine_ids[0] === m.machine_id) ?? parent.incident_id;
      m.scenario = sc.key;
      m.severity = severity;
      m.status = severity === "critical" || severity === "high" ? "needs_intervention" : m.status === "silent" ? "silent" : "operational";
      m.health_score = Math.min(m.health_score, health + Math.round(this.rand() * 6));
      m.top_factors = this.factors(sc);
      this.refreshRisk(m);
    }

    const label = group ? `Incidente grupal en ${ZONE(parent.zone)}: ${ms.length} máquinas` : `${sc.label} en ${ms[0]!.machine_id}`;
    this.post(parent.incident_id, SYSTEM, `AnomalyDetected → ${label}. Severidad ${severity}. Generando diagnóstico IA…`, at);
    this.notify({ at: iso(at), kind: "incident.detected", severity, title: label, body: sc.label, incident_id: parent.incident_id, machine_id: ms[0]!.machine_id, zone: parent.zone });
    this.touch("incidents", "machines");
    return parent;
  }

  /** Rama Parallel "diagnóstico IA" (ia-gemini diagnose / common_cause). */
  private diagnose(inc: IncidentState, at: number) {
    const sc = SCENARIO_BY_KEY.get(inc.scenario)!;
    const m = this.machines.get(inc.machine_ids[0]!)!;
    const group = inc.child_incident_ids.length > 0;
    inc.ai_diagnosis = this.diagnosis(sc, m, 0.66 + this.rand() * 0.25, group ? GROUP_CAUSE.cause : null);
    if (group) {
      inc.ai_diagnosis.suggested_action = GROUP_CAUSE.action;
      for (const ch of this.children(inc)) ch.ai_diagnosis = { ...inc.ai_diagnosis };
    }
    inc.aiAt = Infinity;
    this.post(inc.incident_id, SYSTEM, `Diagnóstico IA (${Math.round(inc.ai_diagnosis.confidence * 100)}%): ${inc.ai_diagnosis.probable_cause}.`, at);
    this.touch("incidents");
  }

  private location(inc: IncidentState): Location {
    return this.machines.get(inc.machine_ids[0]!)!.location;
  }

  /** scoring-tecnicos + Map de notificaciones. */
  private assignBest(inc: IncidentState, at: number) {
    const techs = [...this.techs.values()];
    inc.candidates = scoreTechnicians(techs, { location: this.location(inc), severity: inc.severity, specialty: inc.specialty }, inc.rejected);
    const best = inc.candidates.find((c) => this.techs.get(c.technician_id)!.available) ?? inc.candidates[0];
    if (!best) return;
    this.assignTo(inc, best.technician_id, at, SYSTEM);
  }

  private assignTo(inc: IncidentState, techId: string, at: number, by: Actor, reason?: string) {
    const prev = inc.assigned_technician_id;
    if (prev && prev !== techId) this.release(prev);
    const tech = this.techs.get(techId)!;
    if (!inc.candidates.length) {
      inc.candidates = scoreTechnicians([...this.techs.values()], { location: this.location(inc), severity: inc.severity, specialty: inc.specialty }, inc.rejected);
    }
    const cand = inc.candidates.find((c) => c.technician_id === techId);
    if (prev !== techId) tech.current_load += 1;
    inc.assigned_technician_id = techId;
    inc.technician_score = cand?.score ?? null;
    inc.assigned_at = iso(at);
    inc.accepted_at = null;
    inc.status = "assigned";
    inc.assignAt = Infinity;
    inc.ackDeadline = at + (techId === PROTECTED_TECH ? T.ackTimeoutProtected : T.ackTimeout);
    inc.autoAckAt = at + T.autoAck + this.rand() * 10_000;
    this.syncChildren(inc);
    const eta = cand?.eta_min ?? etaMinutes(tech.location, this.location(inc));
    const how = by === SYSTEM ? `Scoring: ${tech.name} (puntaje ${cand?.score ?? "—"}, ETA ${eta} min)` : `${by.name} reasignó a ${tech.name}${reason ? `: ${reason}` : ""}`;
    this.post(inc.incident_id, SYSTEM, `${how}. Notificación push + email enviada. Esperando aceptación…`, at);
    this.notify({ at: iso(at), kind: "incident.assigned", severity: inc.severity, title: `${inc.incident_id} asignado a ${tech.name}`, body: `ETA ${eta} min`, incident_id: inc.incident_id, zone: inc.zone, technician_id: techId });
    this.touch("incidents", "technicians");
  }

  private release(techId: string) {
    const t = this.techs.get(techId);
    if (!t) return;
    t.current_load = Math.max(0, t.current_load - 1);
    if (t.current_load === 0) {
      t.available = true;
      t.target = null;
    }
    this.touch("technicians");
  }

  private accept(inc: IncidentState, at: number) {
    inc.status = "in_progress";
    inc.accepted_at = iso(at);
    inc.ackDeadline = Infinity;
    inc.autoAckAt = Infinity;
    inc.autoResolveAt = at + T.autoResolve + this.rand() * 30_000;
    const tech = this.techs.get(inc.assigned_technician_id!)!;
    tech.available = false;
    tech.target = { ...this.location(inc) };
    this.syncChildren(inc);
    this.applyToMachines(inc, (m) => {
      if (m.severity === "critical") m.status = "stopped";
    });
    this.post(inc.incident_id, { user_id: tech.user_id, role: "tecnico", name: tech.name }, "Acepto el incidente. Voy en camino.", at, "accept");
    this.notify({ at: iso(at), kind: "incident.accepted", severity: inc.severity, title: `${tech.name} aceptó ${inc.incident_id}`, body: "En camino", incident_id: inc.incident_id, zone: inc.zone, technician_id: tech.technician_id });
    this.touch("incidents", "technicians");
  }

  private escalate(inc: IncidentState, at: number) {
    const prev = inc.assigned_technician_id;
    inc.escalated = true;
    if (prev) inc.rejected.push(prev);
    this.post(inc.incident_id, SYSTEM, `Timeout de aceptación: ${this.techName(prev)} no respondió. Escalando al supervisor y reasignando.`, at);
    this.notify({ at: iso(at), kind: "incident.escalated", severity: inc.severity, title: `${inc.incident_id} escalado`, body: `Sin respuesta de ${this.techName(prev)}`, incident_id: inc.incident_id, zone: inc.zone });
    this.assignBest(inc, at);
  }

  private resolveInternal(inc: IncidentState, at: number, notes: string, components: string[], cost: number | undefined, by: Actor) {
    inc.status = "resolved";
    inc.resolved_at = iso(at);
    inc.autoResolveAt = Infinity;
    inc.closeAt = at + T.close;
    const m = this.machines.get(inc.machine_ids[0]!)!;
    inc.components_replaced = components.length ? components : this.partsFor(m.model, inc.specialty);
    inc.cost_usd = cost ?? inc.components_replaced.reduce((a, c) => a + (COMPONENT_BY_ID.get(c)?.cost_usd ?? 0), 0) + 320;
    this.syncChildren(inc);
    this.post(inc.incident_id, by, notes || "Trabajo terminado, equipo probado.", at, "resolve");
    this.post(inc.incident_id, SYSTEM, "Resolución recibida (resolve_token). Generando resumen IA y cerrando…", at + 500);
    this.touch("incidents");
  }

  /** Cierre: resumen IA, MTTR, descuento de inventario y MaintenanceRecord. */
  private close(inc: IncidentState, at: number) {
    const sc = SCENARIO_BY_KEY.get(inc.scenario)!;
    const group = inc.child_incident_ids.length > 0;
    inc.status = "closed";
    inc.closeAt = Infinity;
    inc.downtime_minutes = Math.round((new Date(inc.resolved_at!).getTime() - new Date(inc.detected_at).getTime()) / 60000);
    const notes = (this.messages.get(inc.incident_id) ?? []).filter((x) => x.quick_action === "resolve").pop()?.text;
    inc.resolution_summary = `${group ? GROUP_CAUSE.summary : sc.summary}${notes ? ` Nota del técnico: «${notes}».` : ""} Tiempo fuera de servicio: ${inc.downtime_minutes} min.`;
    this.syncChildren(inc);

    const tech = inc.assigned_technician_id ? this.techs.get(inc.assigned_technician_id) : undefined;
    const wh = tech?.home_warehouse_id ?? "WH-01";
    for (const c of inc.components_replaced) {
      const item = this.inventory.find((i) => i.warehouse_id === wh && i.component_id === c) ?? this.inventory.find((i) => i.component_id === c);
      if (!item) continue;
      item.stock = Math.max(0, item.stock - 1);
      item.alert = item.stock < item.stock_min ? "low_stock" : item.stock > item.stock_max ? "overstock" : "none";
      if (item.alert === "low_stock") {
        this.notify({ at: iso(at), kind: "parts.shortage", severity: "medium", title: `Stock bajo: ${item.name}`, body: `${item.warehouse_id}: ${item.stock}/${item.stock_min}`, zone: item.zone });
      }
    }
    this.touch("inventory");

    this.applyToMachines(inc, (m) => {
      m.open_incident_id = null;
      m.scenario = null;
      m.status = "operational";
      m.severity = "info";
      m.top_factors = [];
      m.health_score = Math.max(m.baseHealth, 88);
      m.last_maintenance_at = iso(at).slice(0, 10);
      this.refreshRisk(m);
      this.records.push({ machine_id: m.machine_id, performed_at: iso(at).slice(0, 10), type: "corrective", components: inc.components_replaced, cost_usd: inc.cost_usd ?? 0, ref_id: inc.incident_id });
    });
    if (tech) this.release(tech.technician_id);
    this.post(inc.incident_id, SYSTEM, `Incidente cerrado. Resumen IA: ${inc.resolution_summary}`, at);
    this.notify({ at: iso(at), kind: "incident.closed", severity: "info", title: `${inc.incident_id} cerrado`, body: `MTTR ${inc.downtime_minutes} min`, incident_id: inc.incident_id, zone: inc.zone });
    this.touch("incidents", "machines", "technicians");
  }

  // ---------------------------------------------------------------- reloj
  tick(now: number) {
    // Telemetría: posiciones, última lectura y salud (≈ procesar escribiendo MachineState)
    for (const m of this.machines.values()) {
      if (m.status === "silent") continue;
      m.last_seen_at = iso(now - Math.floor(this.rand() * 4000));
      this.events += 1;
      if ((m.type === "mining_truck" || m.type === "loader") && m.status === "operational") {
        const r = m.type === "mining_truck" ? 0.006 : 0.003;
        m.location = {
          lat: clamp(m.location.lat + gaussian(this.rand) * 0.0004, m.home.lat - r, m.home.lat + r),
          lon: clamp(m.location.lon + gaussian(this.rand) * 0.0004, m.home.lon - r, m.home.lon + r),
          zone: m.home.zone,
        };
      }
      if (m.scenario && m.status !== "stopped") {
        m.health_score = Math.max(12, m.health_score - (this.rand() < 0.3 ? 1 : 0));
        this.refreshRisk(m);
      }
    }
    // Silencio (heartbeat): la máquina vuelve a reportar tras ~4 min
    for (const m of this.machines.values()) {
      if (m.status === "silent" && m.silentSince && now - m.silentSince > 13 * 60_000) {
        m.status = "operational";
        m.silentSince = undefined;
      }
    }
    // Técnicos en camino
    for (const t of this.techs.values()) {
      const dest = t.target ?? (t.current_load === 0 ? t.home : null);
      if (!dest) continue;
      const dLat = dest.lat - t.location.lat;
      const dLon = dest.lon - t.location.lon;
      if (Math.abs(dLat) + Math.abs(dLon) < 0.00005) continue;
      t.location = { lat: t.location.lat + dLat * 0.12, lon: t.location.lon + dLon * 0.12, zone: t.location.zone };
      this.touch("technicians");
    }
    // Máquina de estados de cada incidente (solo padres / individuales)
    for (const inc of [...this.incidents.values()]) {
      if (!OPEN(inc) || inc.parent_incident_id) continue;
      if (!inc.ai_diagnosis && now >= inc.aiAt) this.diagnose(inc, now);
      if (inc.status === "detected" && now >= inc.assignAt) this.assignBest(inc, now);
      const autoTech = inc.assigned_technician_id !== PROTECTED_TECH;
      if (inc.status === "assigned") {
        if (this.autopilot && autoTech && now >= inc.autoAckAt) this.accept(inc, now);
        else if (now >= inc.ackDeadline) this.escalate(inc, now);
      }
      if (inc.status === "in_progress" && this.autopilot && autoTech && now >= inc.autoResolveAt) {
        this.resolveInternal(inc, now, "", [], undefined, this.techActor(inc.assigned_technician_id!));
      }
      if (inc.status === "resolved" && now >= inc.closeAt) this.close(inc, now);
    }
    // Respuestas automáticas en el chat
    for (const r of this.replies.filter((x) => x.at <= now)) this.post(r.incidentId, r.actor, r.text, now);
    this.replies = this.replies.filter((x) => x.at > now);
    // Nuevas anomalías
    if (this.autopilot && now >= this.nextSpawnAt) {
      this.nextSpawnAt = now + T.spawnMin + this.rand() * (T.spawnMax - T.spawnMin);
      this.spawn(now);
    }
    this.touch("machines");
    this.flush();
  }

  private spawn(now: number) {
    const open = [...this.incidents.values()].filter((i) => OPEN(i) && !i.parent_incident_id).length;
    if (open >= MAX_OPEN) return;
    const free = [...this.machines.values()].filter((m) => !m.open_incident_id && m.status === "operational");
    if (!free.length) return;
    if (this.rand() < 0.15) {
      const zone = pick(this.rand, ZONES);
      const ms = free.filter((m) => m.home.zone === zone).slice(0, 3);
      if (ms.length === 3) {
        this.detect(ms.map((m) => m.machine_id), "combustible", now, true);
        return;
      }
    }
    const m = pick(this.rand, free);
    this.detect([m.machine_id], this.scenarioFor(m).key, now);
  }

  private techActor(techId: string): Actor {
    const t = this.techs.get(techId)!;
    return { user_id: t.user_id, role: "tecnico", name: t.name, technician_id: techId };
  }

  // ---------------------------------------------------------------- comandos (≈ api-comandos)
  private openIncident(id: string): IncidentState {
    const inc = this.incidents.get(id);
    if (!inc) throw new ApiError(404, "NOT_FOUND", `No existe el incidente ${id}`);
    if (inc.parent_incident_id) {
      throw new ApiError(409, "INCIDENT_STATE_INVALID", `Es parte del incidente grupal ${inc.parent_incident_id}; actúa sobre el padre`);
    }
    return inc;
  }

  cmdAck(id: string, decision: "accept" | "reject", actor: Actor, reason?: string): IncidentState {
    const inc = this.openIncident(id);
    if (inc.status !== "assigned") throw new ApiError(409, "INCIDENT_STATE_INVALID", `El incidente está ${inc.status}, no espera aceptación`);
    if (actor.role === "tecnico" && inc.assigned_technician_id !== actor.technician_id) {
      throw new ApiError(403, "FORBIDDEN", "Solo el técnico asignado puede aceptar o rechazar");
    }
    const now = Date.now();
    if (decision === "accept") this.accept(inc, now);
    else {
      const prev = inc.assigned_technician_id!;
      inc.rejected.push(prev);
      this.post(inc.incident_id, actor, `Rechazo la asignación${reason ? `: ${reason}` : ""}.`, now, "reject");
      this.assignBest(inc, now);
    }
    this.flush();
    return inc;
  }

  cmdAssign(id: string, techId: string, actor: Actor, reason?: string): IncidentState {
    const inc = this.openIncident(id);
    if (!["detected", "assigned"].includes(inc.status)) {
      throw new ApiError(409, "INCIDENT_STATE_INVALID", `No se puede reasignar un incidente ${inc.status}`);
    }
    if (!this.techs.has(techId)) throw new ApiError(404, "NOT_FOUND", `No existe el técnico ${techId}`);
    this.assignTo(inc, techId, Date.now(), actor, reason);
    this.flush();
    return inc;
  }

  cmdResolve(id: string, body: { resolution_notes: string; components_replaced?: string[]; cost_usd?: number }, actor: Actor): IncidentState {
    const inc = this.openIncident(id);
    if (inc.status !== "in_progress") throw new ApiError(409, "INCIDENT_STATE_INVALID", `Solo se resuelve un incidente en atención (está ${inc.status})`);
    if (actor.role === "tecnico" && inc.assigned_technician_id !== actor.technician_id) {
      throw new ApiError(403, "FORBIDDEN", "Solo el técnico asignado puede resolver");
    }
    if (!body.resolution_notes?.trim()) {
      throw new ApiError(400, "VALIDATION_ERROR", "resolution_notes es obligatorio", null, [{ field: "resolution_notes", issue: "required" }]);
    }
    this.resolveInternal(inc, Date.now(), body.resolution_notes.trim(), body.components_replaced ?? [], body.cost_usd, actor);
    this.flush();
    return inc;
  }

  cmdMyStatus(techId: string, body: { available?: boolean; location?: Location }) {
    const t = this.techs.get(techId);
    if (!t) throw new ApiError(404, "NOT_FOUND", "Tu usuario no está registrado como técnico");
    if (body.available !== undefined) t.available = body.available;
    if (body.location) t.location = { ...body.location, zone: t.zone };
    this.touch("technicians");
    this.flush();
    return t;
  }

  /** Mensaje del chat (Firestore incidents/{id}/messages). */
  chat(incidentId: string, actor: Actor, text: string, quick?: string | null) {
    const inc = this.incidents.get(incidentId);
    if (!inc) throw new ApiError(404, "NOT_FOUND", "Incidente inexistente");
    if (inc.status === "closed") throw new ApiError(409, "INCIDENT_STATE_INVALID", "El chat de un incidente cerrado es de solo lectura");
    const now = Date.now();
    this.post(incidentId, actor, text, now, quick);
    const tech = inc.assigned_technician_id;
    if (tech && tech !== actor.technician_id && tech !== PROTECTED_TECH && actor.role !== "tecnico") {
      const t = this.techActor(tech);
      const replies = ["Recibido, lo reviso al llegar.", "Entendido. Confirmo en cuanto tenga el diagnóstico en sitio.", "OK, llevo el repuesto sugerido."];
      this.replies.push({ at: now + 4000 + this.rand() * 3000, incidentId, actor: t, text: pick(this.rand, replies) });
    }
    this.flush();
  }

  /** Panel de control del modo demo: inyectar un escenario del simulador a pedido. */
  inject(scenarioKey: string, machineId?: string, zone?: string): IncidentState {
    const now = Date.now();
    if (scenarioKey === "grupal_zona") {
      const z = zone ?? pick(this.rand, ZONES);
      const ms = [...this.machines.values()].filter((m) => m.home.zone === z && !m.open_incident_id && m.status === "operational").slice(0, 3);
      if (ms.length < 2) throw new ApiError(409, "INCIDENT_STATE_INVALID", `No hay suficientes máquinas libres en ${z}`);
      const inc = this.detect(ms.map((m) => m.machine_id), "combustible", now, true);
      this.flush();
      return inc;
    }
    const candidates = [...this.machines.values()].filter((m) => !m.open_incident_id && (!zone || m.home.zone === zone));
    const m = machineId ? this.machines.get(machineId) : pick(this.rand, candidates);
    if (!m) throw new ApiError(404, "NOT_FOUND", "No hay máquina disponible");
    const sc = SCENARIO_BY_KEY.get(scenarioKey) ?? this.scenarioFor(m);
    const inc = this.detect([m.machine_id], sc.key, now);
    this.flush();
    return inc;
  }

  notifyModelTrained(version: string, promoted: boolean) {
    this.notify({ at: iso(Date.now()), kind: "model.trained", severity: "info", title: `Modelo ${version} entrenado`, body: promoted ? "Promovido a producción" : "No promovido: no supera al modelo activo" });
    this.flush();
  }

  // ---------------------------------------------------------------- vistas públicas (copias, como una API)
  publicIncident(inc: IncidentState): Incident {
    const { scenario, specialty, candidates, rejected, aiAt, assignAt, ackDeadline, autoAckAt, autoResolveAt, closeAt, ...pub } = inc;
    void [scenario, specialty, candidates, rejected, aiAt, assignAt, ackDeadline, autoAckAt, autoResolveAt, closeAt];
    return structuredClone(pub);
  }

  publicMachine(m: MachineState): MachineDetail {
    const { home, baseHealth, scenario, silentSince, ...pub } = m;
    void [home, baseHealth, scenario, silentSince];
    return structuredClone(pub);
  }

  publicTech(t: TechState): Technician {
    const { user_id, zone, home, home_warehouse_id, target, ...pub } = t;
    void [user_id, zone, home, home_warehouse_id, target];
    return structuredClone(pub);
  }

  modelOf(machineId: string) {
    return MODEL_BY_ID.get(this.machines.get(machineId)?.model ?? "");
  }
}

const ZONE = (z: string) => `zona ${z}`;
