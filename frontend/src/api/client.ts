import type {
  AssistantAnswer,
  FuelItem,
  Incident,
  IncidentQuery,
  InventoryItem,
  Kpis,
  Machine,
  MachineDetail,
  MachineQuery,
  MaintenancePlanItem,
  Me,
  MlModel,
  Page,
  PartForecast,
  PartRanking,
  ProductivityItem,
  Report,
  ResolveRequest,
  Technician,
  TelemetryPoint,
  Timeline,
} from "./types";

/**
 * Contrato del front con el backend: una operación por ruta de openapi.yaml (stage v1, rutas sin prefijo).
 * Dos implementaciones: HttpApi (API Gateway real) y DemoApi (seeds + simulación).
 * Las vistas solo conocen esta interfaz, así que pasar de demo a real no toca ninguna pantalla.
 */
export interface FleetApi {
  readonly mode: "http" | "demo";

  // Sesión
  me(): Promise<Me>;
  firebaseToken(fcmToken?: string): Promise<{ firebase_token: string; expires_in: number }>;

  // Flota
  listMachines(q?: MachineQuery, limit?: number, cursor?: string): Promise<Page<Machine>>;
  getMachine(id: string): Promise<MachineDetail>;
  getTelemetry(id: string, from: string, to: string, resolution?: "1m" | "1h"): Promise<TelemetryPoint[]>;
  getTimeline(id: string): Promise<Timeline>;

  // Incidentes
  listIncidents(q?: IncidentQuery, limit?: number, cursor?: string): Promise<Page<Incident>>;
  getIncident(id: string): Promise<Incident>;
  ack(id: string, decision: "accept" | "reject", reason?: string): Promise<Incident>;
  assign(id: string, technicianId: string, reason?: string): Promise<Incident>;
  resolve(id: string, body: ResolveRequest): Promise<Incident>;

  // Técnicos
  listTechnicians(q?: { machine_id?: string; available?: boolean; specialty?: string }): Promise<Technician[]>;
  updateMyStatus(body: { available?: boolean; location?: { lat: number; lon: number } }): Promise<Technician>;

  // Mantenimiento y repuestos
  listInventory(q?: { warehouse_id?: string; alert?: "low_stock" | "overstock" }): Promise<InventoryItem[]>;
  partsRanking(): Promise<PartRanking[]>;
  partsForecast(q?: { horizon_days?: 7 | 30 | 90; warehouse_id?: string }): Promise<PartForecast[]>;
  maintenancePlan(q?: { zone?: string; flag?: "overdue" | "unnecessary" }): Promise<MaintenancePlanItem[]>;

  // Analítica
  fuel(q?: { zone?: string; period?: "7d" | "30d" }): Promise<FuelItem[]>;
  productivity(q?: { zone?: string; period?: "7d" | "30d" }): Promise<ProductivityItem[]>;
  kpis(q?: { zone?: string; period?: "7d" | "30d" }): Promise<Kpis>;
  latestReport(type?: "daily" | "weekly"): Promise<Report>;

  // IA
  mlModel(): Promise<MlModel>;
  retrain(): Promise<{ execution_arn: string }>;
  assistant(message: string, sessionId?: string): Promise<AssistantAnswer>;
}

/** Recorre todas las páginas de una lista paginada por cursor (las listas son chicas: ~100 máquinas). */
export async function fetchAll<T>(
  page: (cursor?: string) => Promise<Page<T>>,
  maxPages = 20,
): Promise<T[]> {
  const out: T[] = [];
  let cursor: string | undefined;
  for (let i = 0; i < maxPages; i++) {
    const p = await page(cursor);
    out.push(...p.data);
    if (!p.next_cursor) break;
    cursor = p.next_cursor;
  }
  return out;
}
