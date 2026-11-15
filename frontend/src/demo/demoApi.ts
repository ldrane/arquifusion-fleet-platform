import type { FleetApi } from "@/api/client";
import { ApiError } from "@/api/errors";
import type { IncidentQuery, Machine, MachineQuery, Me, Page, SimStartRequest, SimState } from "@/api/types";
import { type Capability, can } from "@/auth/permissions";
import { SEVERITY_RANK } from "@/lib/format";
import { etaMinutes } from "@/lib/geo";
import { myTechnicianId, newCorrelationId } from "@/lib/ids";
import * as analytics from "./analytics";
import { answer } from "./assistant";
import { DEMO_USERS } from "./data";
import { latestReading, telemetrySeries } from "./telemetry";
import type { Actor, DemoWorld } from "./world";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * FleetApi sobre el mundo simulado. Aplica las MISMAS reglas que el backend:
 * RBAC por rol (x-roles), filtro por zona del usuario, paginación por cursor y errores del contrato.
 */
export class DemoApi implements FleetApi {
  readonly mode = "demo" as const;

  constructor(
    private readonly world: DemoWorld,
    private readonly currentUser: () => Me | null,
  ) {}

  private async guard(cap: Capability): Promise<Me> {
    await sleep(80 + Math.random() * 160); // latencia de red simulada
    const me = this.currentUser();
    if (!me) throw new ApiError(401, "UNAUTHENTICATED", "Falta el JWT de Cognito", newCorrelationId());
    if (!can(me.role, cap)) throw new ApiError(403, "FORBIDDEN", `El rol ${me.role} no puede usar esta operación`, newCorrelationId());
    return me;
  }

  /** Zona efectiva: la del usuario manda; un usuario sin zona puede filtrar por cualquiera. */
  private zoneFor(me: Me, requested?: string) {
    if (me.zone && requested && requested !== me.zone) {
      throw new ApiError(403, "FORBIDDEN", `Tu usuario solo ve la zona ${me.zone}`, newCorrelationId());
    }
    return me.zone ?? requested;
  }

  private actor(me: Me): Actor {
    const demo = DEMO_USERS.find((u) => u.user_id === me.user_id);
    return { user_id: me.user_id, role: me.role, name: demo?.name ?? me.user_id, technician_id: myTechnicianId(me) };
  }

  private paginate<T>(rows: T[], limit = 50, cursor?: string): Page<T> {
    const start = cursor ? Number(atob(cursor)) || 0 : 0;
    const size = Math.min(100, Math.max(1, limit));
    const data = rows.slice(start, start + size);
    const next = start + size < rows.length ? btoa(String(start + size)) : null;
    return { data, next_cursor: next };
  }

  async me() {
    await sleep(60);
    const me = this.currentUser();
    if (!me) throw new ApiError(401, "UNAUTHENTICATED", "Sin sesión");
    return me;
  }

  async firebaseToken() {
    await this.guard("machines");
    return { firebase_token: "demo", expires_in: 3600 };
  }

  async listMachines(q: MachineQuery = {}, limit = 100, cursor?: string): Promise<Page<Machine>> {
    const me = await this.guard("machines");
    const zone = this.zoneFor(me, q.zone);
    const rows = [...this.world.machines.values()]
      .filter((m) => (!zone || m.home.zone === zone) && (!q.type || m.type === q.type) && (!q.status || m.status === q.status) && (!q.severity || m.severity === q.severity))
      .map((m) => {
        const d = this.world.publicMachine(m);
        return {
          machine_id: d.machine_id,
          model: d.model,
          type: d.type,
          location: d.location,
          status: d.status,
          severity: d.severity,
          health_score: d.health_score,
          last_seen_at: d.last_seen_at,
          open_incident_id: d.open_incident_id,
        };
      });
    return this.paginate(rows, limit, cursor);
  }

  async getMachine(id: string) {
    const me = await this.guard("machines");
    const m = this.world.machines.get(id);
    if (!m || (me.zone && m.home.zone !== me.zone)) throw new ApiError(404, "NOT_FOUND", `No existe la máquina ${id}`, newCorrelationId());
    const detail = this.world.publicMachine(m);
    detail.latest_reading = latestReading(this.tm(id), Date.now(), this.degradation(id));
    return detail;
  }

  private tm(id: string) {
    const m = this.world.machines.get(id)!;
    return { machine_id: m.machine_id, model: m.model, type: m.type, baseHealth: m.baseHealth, health: m.health_score, operating_hours: m.operating_hours, location: m.location, status: m.status };
  }

  private degradation(id: string) {
    const m = this.world.machines.get(id)!;
    const inc = m.open_incident_id ? this.world.incidents.get(m.open_incident_id) : undefined;
    return m.scenario && inc ? { scenario: m.scenario, detectedAt: new Date(inc.detected_at).getTime() } : null;
  }

  async getTelemetry(id: string, from: string, to: string, resolution: "1m" | "1h" = "1m") {
    await this.guard("telemetry");
    if (!this.world.machines.has(id)) throw new ApiError(404, "NOT_FOUND", `No existe la máquina ${id}`);
    if (!from || !to || new Date(from) >= new Date(to)) {
      throw new ApiError(400, "VALIDATION_ERROR", "from debe ser anterior a to", null, [{ field: "from", issue: "invalid_range" }]);
    }
    return telemetrySeries(this.tm(id), from, to, resolution, this.degradation(id));
  }

  async getTimeline(id: string) {
    await this.guard("timeline");
    if (!this.world.machines.has(id)) throw new ApiError(404, "NOT_FOUND", `No existe la máquina ${id}`);
    return analytics.timeline(this.world, id);
  }

  async listIncidents(q: IncidentQuery = {}, limit = 100, cursor?: string) {
    const me = await this.guard("incidents");
    const zone = this.zoneFor(me, q.zone);
    const rows = [...this.world.incidents.values()]
      .filter(
        (i) =>
          (!zone || i.zone === zone) &&
          (!q.status || i.status === q.status) &&
          (!q.severity || i.severity === q.severity) &&
          (!q.machine_id || i.machine_ids.includes(q.machine_id)) &&
          (q.parent_incident_id ? i.parent_incident_id === q.parent_incident_id : true),
      )
      // Cola: abiertos primero, luego severidad, luego antigüedad (OpenAPI: "ordenada por severidad y antigüedad")
      .sort(
        (a, b) =>
          Number(a.status === "closed") - Number(b.status === "closed") ||
          SEVERITY_RANK[b.severity] - SEVERITY_RANK[a.severity] ||
          (a.status === "closed" ? b.detected_at.localeCompare(a.detected_at) : a.detected_at.localeCompare(b.detected_at)),
      )
      .map((i) => this.world.publicIncident(i));
    return this.paginate(rows, limit, cursor);
  }

  async getIncident(id: string) {
    const me = await this.guard("incidents");
    const inc = this.world.incidents.get(id);
    if (!inc || (me.zone && inc.zone !== me.zone)) throw new ApiError(404, "NOT_FOUND", `No existe el incidente ${id}`, newCorrelationId());
    return this.world.publicIncident(inc);
  }

  async ack(id: string, decision: "accept" | "reject", reason?: string) {
    const me = await this.guard("ack");
    return this.world.publicIncident(this.world.cmdAck(id, decision, this.actor(me), reason));
  }

  async assign(id: string, technicianId: string, reason?: string) {
    const me = await this.guard("assign");
    return this.world.publicIncident(this.world.cmdAssign(id, technicianId, this.actor(me), reason));
  }

  async resolve(id: string, body: { resolution_notes: string; components_replaced?: string[]; cost_usd?: number }) {
    const me = await this.guard("resolve");
    return this.world.publicIncident(this.world.cmdResolve(id, body, this.actor(me)));
  }

  async listTechnicians(q: { machine_id?: string; available?: boolean; specialty?: string } = {}) {
    const me = await this.guard("technicians");
    const target = q.machine_id ? this.world.machines.get(q.machine_id) : undefined;
    return [...this.world.techs.values()]
      .filter((t) => (!me.zone || t.zone === me.zone) && (q.available === undefined || t.available === q.available) && (!q.specialty || t.specialties.includes(q.specialty as never)))
      .map((t) => ({ ...this.world.publicTech(t), eta_minutes: target ? etaMinutes(t.location, target.location) : null }));
  }

  async updateMyStatus(body: { available?: boolean; location?: { lat: number; lon: number } }) {
    const me = await this.guard("myStatus");
    const techId = myTechnicianId(me);
    return this.world.publicTech(this.world.cmdMyStatus(techId ?? "", body));
  }

  async listInventory(q: { warehouse_id?: string; alert?: "low_stock" | "overstock" } = {}) {
    await this.guard("inventory");
    return this.world.inventory
      .filter((i) => (!q.warehouse_id || i.warehouse_id === q.warehouse_id) && (!q.alert || i.alert === q.alert))
      .map(({ zone, ...i }) => (void zone, { ...i }));
  }

  async partsRanking() {
    await this.guard("partsRanking");
    return analytics.partsRanking(this.world);
  }

  async partsForecast(q: { horizon_days?: 7 | 30 | 90; warehouse_id?: string } = {}) {
    await this.guard("partsForecast");
    return analytics.partsForecast(this.world, q.horizon_days ?? 30, q.warehouse_id);
  }

  async maintenancePlan(q: { zone?: string; flag?: "overdue" | "unnecessary" } = {}) {
    const me = await this.guard("maintenancePlan");
    const zone = this.zoneFor(me, q.zone);
    return analytics.maintenancePlan(this.world).filter((p) => (!zone || p.zone === zone) && (!q.flag || p.flag === q.flag));
  }

  async fuel(q: { zone?: string; period?: "7d" | "30d" } = {}) {
    const me = await this.guard("fuel");
    return analytics.fuel(this.world, this.zoneFor(me, q.zone));
  }

  async productivity(q: { zone?: string; period?: "7d" | "30d" } = {}) {
    const me = await this.guard("productivity");
    return analytics.productivity(this.world, this.zoneFor(me, q.zone));
  }

  async kpis(q: { zone?: string; period?: "7d" | "30d" } = {}) {
    const me = await this.guard("kpis");
    return analytics.kpis(this.world, this.zoneFor(me, q.zone), q.period ?? "7d");
  }

  async precursors() {
    await this.guard("precursors");
    return analytics.precursors(this.world);
  }

  async latestReport() {
    await this.guard("report");
    return analytics.report(this.world);
  }

  private model = { model_version: "v3", trained_at: new Date(Date.now() - 3 * 86400_000).toISOString(), precision: 0.87, recall: 0.81, mean_lead_time_hours: 18.5, promoted: true };

  async mlModel() {
    await this.guard("mlModel");
    return { ...this.model };
  }

  async retrain() {
    await this.guard("retrain");
    const arn = `arn:aws:states:us-east-1:000000000000:execution:arquifusion-dev-reentrenamiento:demo-${Date.now()}`;
    setTimeout(() => {
      // Reentrenamiento: entrena, evalúa y solo promueve si mejora (MH-AI-04)
      const recall = 0.79 + Math.random() * 0.06;
      const promoted = recall > this.model.recall;
      const version = `v${Number(this.model.model_version.slice(1)) + 1}`;
      if (promoted) this.model = { model_version: version, trained_at: new Date().toISOString(), precision: 0.88, recall: Math.round(recall * 100) / 100, mean_lead_time_hours: 19.2, promoted: true };
      this.world.notifyModelTrained(version, promoted);
    }, 9000);
    return { execution_arn: arn };
  }

  async assistant(message: string, sessionId?: string) {
    const me = await this.guard("assistant");
    await sleep(500 + Math.random() * 700);
    if (!message.trim() || message.length > 1000) {
      throw new ApiError(400, "VALIDATION_ERROR", "El mensaje debe tener entre 1 y 1000 caracteres", null, [{ field: "message", issue: "length" }]);
    }
    return answer(this.world, me, message, sessionId);
  }

  // ---------------------------------------------------------------- simulador serverless (demo)
  private sim: SimState = { enabled: false };

  async simState() {
    await this.guard("simulate");
    return { ...this.sim };
  }

  async simStart(body: SimStartRequest) {
    const me = await this.guard("simulate");
    if (!body.scenario) throw new ApiError(400, "VALIDATION_ERROR", "scenario es obligatorio", newCorrelationId(), [{ field: "scenario" }]);
    // En demo el efecto es inmediato en el mundo local (mismo botón que en AWS real).
    this.world.inject(body.scenario, body.machines?.[0], body.zone ?? undefined);
    const now = Date.now();
    const minutes = body.duration_min ?? 20;
    this.sim = {
      enabled: true,
      scenario: body.scenario,
      machines: body.machines ?? [],
      zone: body.zone ?? null,
      speedup: body.speedup ?? 240,
      interval_s: body.interval_s ?? 10,
      started_at: new Date(now).toISOString(),
      expires_at: new Date(now + minutes * 60_000).toISOString(),
      requested_by: me.user_id,
      correlation_id: newCorrelationId(),
    };
    return { ...this.sim };
  }

  async simStop() {
    await this.guard("simulate");
    this.sim = { ...this.sim, enabled: false };
    return { ...this.sim };
  }

  // ---------------------------------------------------------------- pulso del sistema (TAREA-14)
  async pulse() {
    await this.guard("pulse");
    const now = Date.now();
    const machines = [...this.world.machines.values()];
    const seen = machines.map((m) => m.last_seen_at).filter((s): s is string => !!s).sort();
    const cutoff = new Date(now - 5 * 60_000).toISOString();
    const incidents = [...this.world.incidents.values()];
    const lastAi = incidents
      .filter((i) => i.ai_diagnosis)
      .sort((a, b) => (a.detected_at < b.detected_at ? 1 : -1))[0];
    return {
      mode: "demo" as const, // el badge del Header lo pinta gris: en el navegador no hay AWS real
      region: "demo",
      last_reading_at: seen.length ? seen[seen.length - 1]! : null,
      machines_reporting_5m: machines.filter((m) => (m.last_seen_at ?? "") >= cutoff).length,
      open_incidents: incidents.filter((i) => i.status !== "closed" && !i.parent_incident_id).length,
      model_version: this.model.model_version,
      last_report_at: analytics.report(this.world).generated_at,
      ai: {
        last_provider: lastAi?.ai_diagnosis?.provider ?? null,
        degraded: Boolean(lastAi?.ai_diagnosis?.degraded),
      },
      generated_at: new Date(now).toISOString(),
    };
  }
}
