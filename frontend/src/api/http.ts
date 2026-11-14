import { newCorrelationId } from "@/lib/ids";
import type { FleetApi } from "./client";
import { ApiError, type ErrorCode } from "./errors";
import type { IncidentQuery, MachineQuery, Page } from "./types";

export interface TokenProvider {
  /** ID token vigente (refresca si hace falta). null = sin sesión. */
  getIdToken(): Promise<string | null>;
  /** Se llama ante un 401 que sobrevive al refresh: cierra la sesión. */
  onUnauthorized(): void;
}

type Query = Record<string, string | number | boolean | undefined | null>;

function qs(q?: Query): string {
  if (!q) return "";
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}

/** Cliente de la API real (API Gateway + Cognito authorizer). Respeta el envoltorio {data, meta}. */
export class HttpApi implements FleetApi {
  readonly mode = "http" as const;

  constructor(
    private readonly baseUrl: string,
    private readonly tokens: TokenProvider,
  ) {}

  private async request<T>(method: string, path: string, opts: { query?: Query; body?: unknown } = {}) {
    const cid = newCorrelationId();
    const token = await this.tokens.getIdToken();
    let res: Response;
    try {
      res = await fetch(`${this.baseUrl}${path}${qs(opts.query)}`, {
        method,
        headers: {
          "Content-Type": "application/json",
          "X-Correlation-Id": cid,
          ...(token ? { Authorization: token } : {}),
        },
        body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      });
    } catch {
      throw new ApiError(0, "NETWORK", "No se pudo conectar con la API (¿CORS o red?)", cid);
    }
    const correlationId = res.headers.get("X-Correlation-Id") ?? cid;
    const json = await res.json().catch(() => null);
    if (!res.ok) {
      if (res.status === 401) this.tokens.onUnauthorized();
      const e = json?.error ?? {};
      throw new ApiError(
        res.status,
        (e.code as ErrorCode) ?? (res.status === 403 ? "FORBIDDEN" : "INTERNAL"),
        e.message ?? json?.message ?? `HTTP ${res.status}`,
        json?.correlation_id ?? correlationId,
        e.details ?? [],
      );
    }
    return { data: json?.data as T, meta: (json?.meta ?? {}) as { next_cursor?: string | null } };
  }

  private async get<T>(path: string, query?: Query): Promise<T> {
    return (await this.request<T>("GET", path, { query })).data;
  }

  private async page<T>(path: string, query: Query): Promise<Page<T>> {
    const r = await this.request<T[]>("GET", path, { query });
    return { data: r.data ?? [], next_cursor: r.meta.next_cursor ?? null };
  }

  private async post<T>(path: string, body?: unknown, method = "POST"): Promise<T> {
    return (await this.request<T>(method, path, { body: body ?? {} })).data;
  }

  me = () => this.get<any>("/v1/me");
  firebaseToken = (fcm_token?: string) => this.post<any>("/v1/auth/firebase-token", fcm_token ? { fcm_token } : {});

  listMachines = (q: MachineQuery = {}, limit = 100, cursor?: string) =>
    this.page<any>("/v1/machines", { ...q, limit, cursor });
  getMachine = (id: string) => this.get<any>(`/v1/machines/${encodeURIComponent(id)}`);
  getTelemetry = (id: string, from: string, to: string, resolution: "1m" | "1h" = "1m") =>
    this.get<any>(`/v1/machines/${encodeURIComponent(id)}/telemetry`, { from, to, resolution });
  getTimeline = (id: string) => this.get<any>(`/v1/machines/${encodeURIComponent(id)}/timeline`);

  listIncidents = (q: IncidentQuery = {}, limit = 100, cursor?: string) =>
    this.page<any>("/v1/incidents", { ...q, limit, cursor });
  getIncident = (id: string) => this.get<any>(`/v1/incidents/${encodeURIComponent(id)}`);
  ack = (id: string, decision: "accept" | "reject", reason?: string) =>
    this.post<any>(`/v1/incidents/${encodeURIComponent(id)}/ack`, { decision, ...(reason ? { reason } : {}) });
  assign = (id: string, technician_id: string, reason?: string) =>
    this.post<any>(`/v1/incidents/${encodeURIComponent(id)}/assign`, { technician_id, ...(reason ? { reason } : {}) });
  resolve = (id: string, body: any) => this.post<any>(`/v1/incidents/${encodeURIComponent(id)}/resolve`, body);

  listTechnicians = (q: Query = {}) => this.get<any>("/v1/technicians", q);
  updateMyStatus = (body: any) => this.post<any>("/v1/technicians/me/status", body, "PUT");

  listInventory = (q: Query = {}) => this.get<any>("/v1/inventory", q);
  partsRanking = () => this.get<any>("/v1/parts/ranking");
  partsForecast = (q: Query = {}) => this.get<any>("/v1/parts/forecast", q);
  maintenancePlan = (q: Query = {}) => this.get<any>("/v1/maintenance/plan", q);

  fuel = (q: Query = {}) => this.get<any>("/v1/analytics/fuel", q);
  productivity = (q: Query = {}) => this.get<any>("/v1/analytics/productivity", q);
  kpis = (q: Query = {}) => this.get<any>("/v1/analytics/kpis", q);
  latestReport = (type: "daily" | "weekly" = "daily") => this.get<any>("/v1/reports/latest", { type });

  mlModel = () => this.get<any>("/v1/ml/model");
  retrain = () => this.post<any>("/v1/ml/retrain");
  assistant = (message: string, session_id?: string) =>
    this.post<any>("/v1/assistant/chat", { message, ...(session_id ? { session_id } : {}) });
}
