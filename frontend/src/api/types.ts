/**
 * Tipos de dominio: espejo 1:1 de contracts/openapi.yaml (components.schemas) y de contratos.md §5.
 * Si cambia el contrato, se cambia aquí y TypeScript marca todo lo que hay que ajustar.
 */

export type Severity = "info" | "low" | "medium" | "high" | "critical";
export type MachineStatus = "operational" | "stopped" | "maintenance" | "needs_intervention" | "silent";
export type MachineType = "excavator" | "mining_truck" | "loader" | "bulldozer" | "drill";
export type IncidentStatus = "detected" | "assigned" | "in_progress" | "resolved" | "closed";
export type Role = "operador" | "tecnico" | "mantenimiento" | "supervisor" | "admin" | "gerencia";
export type Specialty = "motor" | "hidraulica" | "electrica" | "neumaticos";
export type Zone = string;

export const SEVERITIES: Severity[] = ["info", "low", "medium", "high", "critical"];
export const ROLES: Role[] = ["operador", "tecnico", "mantenimiento", "supervisor", "admin", "gerencia"];

export interface Location {
  lat: number;
  lon: number;
  zone?: Zone;
}

export interface Aggregate {
  min: number;
  avg: number;
  max: number;
}

export interface Factor {
  variable: string;
  z_score: number;
  direction: "high" | "low";
}

export interface TelemetryReading {
  machine_id: string;
  model: string;
  type: MachineType;
  timestamp: string;
  location: Location;
  operating_hours: number;
  temperature_c: number;
  vibration_mm_s: number;
  pressure_bar: number;
  fuel_rate_lph: number;
  load_pct: number;
  speed_kmh: number;
  rpm: number;
  state: "operating" | "idle" | "stopped" | "maintenance";
  sim_scenario?: string | null;
}

export interface Machine {
  machine_id: string;
  model: string;
  type: MachineType;
  location: Location;
  status: MachineStatus;
  severity: Severity;
  health_score: number;
  last_seen_at: string | null;
  /** Firestore/Dynamo lo traen (contratos.md §9); el OpenAPI lo expone en MachineDetail. */
  open_incident_id?: string | null;
}

export interface MachineDetail extends Machine {
  failure_probability: number | null;
  rul_hours: number | null;
  operating_hours: number;
  last_maintenance_at: string | null;
  next_maintenance_at: string | null;
  open_incident_id: string | null;
  latest_reading?: TelemetryReading | null;
  top_factors: Factor[];
  model_version: string | null;
}

export interface AiDiagnosis {
  probable_cause: string;
  suggested_action: string;
  common_cause?: string | null;
  top_factors: Factor[];
  confidence: number;
  model_version: string;
  prompt_version: string;
  degraded: boolean;
}

export interface Incident {
  incident_id: string;
  parent_incident_id: string | null;
  child_incident_ids: string[];
  machine_ids: string[];
  zone: Zone;
  severity: Severity;
  status: IncidentStatus;
  escalated: boolean;
  is_recurrence: boolean;
  assigned_technician_id: string | null;
  technician_score: number | null;
  ai_diagnosis: AiDiagnosis | null;
  resolution_summary: string | null;
  detected_at: string;
  assigned_at: string | null;
  accepted_at: string | null;
  resolved_at: string | null;
  downtime_minutes: number | null;
  components_replaced: string[];
  cost_usd: number | null;
  chat_channel_id: string | null;
}

export interface Technician {
  technician_id: string;
  name: string;
  specialties: Specialty[];
  location: Location;
  available: boolean;
  shift: "day" | "night";
  current_load: number;
  eta_minutes?: number | null;
}

export interface InventoryItem {
  warehouse_id: string;
  component_id: string;
  name: string;
  stock: number;
  stock_min: number;
  stock_max: number;
  alert: "none" | "low_stock" | "overstock";
}

export interface Me {
  user_id: string;
  email: string | null;
  role: Role;
  zone: Zone | null;
}

export interface TelemetryPoint {
  bucket_start: string;
  temperature_c: Aggregate;
  vibration_mm_s: Aggregate;
  pressure_bar: Aggregate;
  fuel_rate_lph: Aggregate;
  health_score: number;
}

export interface TimelineEvent {
  at: string;
  kind: "incident" | "preventive" | "corrective" | "anomaly";
  ref_id: string;
  summary: string;
}

export interface Timeline {
  events: TimelineEvent[];
  kpis: { mtbf_hours: number; mttr_hours: number; availability_pct: number };
}

export interface PartRanking {
  component_id: string;
  name: string;
  units_used_90d: number;
  irregular_consumption: boolean;
}

export interface PartForecast {
  warehouse_id: string;
  component_id: string;
  expected_demand: number;
  stock: number;
  recommended_min: number;
  recommended_max: number;
  shortage_for_planned_maintenance: boolean;
}

export interface MaintenancePlanItem {
  machine_id: string;
  zone: Zone;
  next_maintenance_at: string;
  priority: number;
  flag: "overdue" | "unnecessary" | "on_track";
  reason: string;
}

export interface FuelItem {
  machine_id: string;
  zone: Zone;
  lph: number;
  l_per_ton: number;
  vs_peers_pct: number;
  vs_own_history_pct: number;
  progressive_increase: boolean;
  probable_causes: string[];
}

export interface ProductivityItem {
  machine_id: string;
  zone: Zone;
  utilization_pct: number;
  classification: "underused" | "normal" | "overused";
  cost_per_hour_usd: number;
  quadrant: "high_prod_low_cost" | "high_prod_high_cost" | "low_prod_low_cost" | "low_prod_high_cost";
  redistribution_suggestion: string | null;
}

export interface Kpis {
  availability_pct: number;
  mtbf_hours: number;
  mttr_hours: number;
  open_incidents: number;
  machines_at_risk: number;
  fleet_utilization_pct: number;
  fuel_cost_per_ton_usd: number;
}

export interface Report {
  generated_at: string;
  summary_text: string;
  prompt_version: string;
  figures: Record<string, unknown>;
}

export interface MlModel {
  model_version: string;
  trained_at: string;
  precision: number;
  recall: number;
  mean_lead_time_hours: number;
  promoted: boolean;
}

export interface AssistantAnswer {
  answer: string;
  session_id: string;
  tools_used: string[];
  degraded: boolean;
}

/** incidents/{id}/messages/{msg_id} (contratos.md §5). */
export interface ChatMessage {
  id: string;
  author_id: string;
  role: Role | "sistema";
  text: string;
  quick_action?: string | null;
  attachment_path?: string | null;
  created_at: string;
  correlation_id: string;
  /** Escrito en caché local de Firestore, aún no confirmado por el servidor (modo offline). */
  pending?: boolean;
}

export interface Page<T> {
  data: T[];
  next_cursor: string | null;
}

export interface MachineQuery {
  zone?: string;
  type?: MachineType;
  status?: MachineStatus;
  severity?: Severity;
}

export interface IncidentQuery {
  status?: IncidentStatus;
  severity?: Severity;
  zone?: string;
  machine_id?: string;
  parent_incident_id?: string;
}

export interface ResolveRequest {
  resolution_notes: string;
  components_replaced?: string[];
  cost_usd?: number;
}
