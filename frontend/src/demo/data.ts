/**
 * Datos maestros del modo demo: se importan DIRECTAMENTE de contracts/fixtures/seed (C1),
 * así el front demo y DynamoDB usan los mismos IDs, modelos, zonas y coordenadas.
 */
import catalogJson from "@seed/catalog.json";
import inventoryJson from "@seed/inventory.json";
import machineModelsJson from "@seed/machine_models.json";
import machinesJson from "@seed/machines.json";
import techniciansJson from "@seed/technicians.json";
import warehousesJson from "@seed/warehouses.json";
import type { Location, MachineType, Severity, Specialty } from "@/api/types";

export interface SeedMachine {
  machine_id: string;
  operation_id: string;
  model: string;
  type: MachineType;
  zone: string;
  location: Location;
  home_location: Location;
  health_score: number;
  operating_hours: number;
  last_maintenance_at: string;
  next_maintenance_at: string;
}

export interface SeedModel {
  model_id: string;
  brand: string;
  type: MachineType;
  payload_t: number;
  maintenance_interval_h: number;
  nominal: Record<string, [number, number]>;
  component_ids: string[];
}

export interface SeedTechnician {
  technician_id: string;
  user_id: string;
  name: string;
  zone: string;
  specialties: Specialty[];
  location: Location;
  home_warehouse_id: string;
  available: boolean;
  shift: "day" | "night";
  current_load: number;
}

export interface SeedComponent {
  component_id: string;
  name: string;
  specialty: Specialty;
  compatible_models: string[];
  cost_usd: number;
  lead_time_days: number;
}

export interface SeedInventory {
  warehouse_id: string;
  zone: string;
  component_id: string;
  name: string;
  stock: number;
  stock_min: number;
  stock_max: number;
  alert: "none" | "low_stock" | "overstock";
}

export interface SeedWarehouse {
  warehouse_id: string;
  name: string;
  zone: string;
  location: Location;
}

export const SEED = {
  machines: machinesJson as unknown as SeedMachine[],
  models: machineModelsJson as unknown as SeedModel[],
  technicians: techniciansJson as unknown as SeedTechnician[],
  catalog: catalogJson as unknown as SeedComponent[],
  inventory: inventoryJson as unknown as SeedInventory[],
  warehouses: warehousesJson as unknown as SeedWarehouse[],
};

export const MODEL_BY_ID = new Map(SEED.models.map((m) => [m.model_id, m]));
export const COMPONENT_BY_ID = new Map(SEED.catalog.map((c) => [c.component_id, c]));
export const ZONES = ["norte", "sur", "este", "oeste"];

/** Usuarios demo = los del runbook H0 (docs/h0-persona-c.md, acuerdo 5 con B). */
export const DEMO_USERS = [
  { user_id: "u-op-01", name: "Rosa Quispe", email: "op01@demo.arquifusion.local", role: "operador", zone: "norte" },
  // El técnico demo ES TEC-07 de los seeds: mismo nombre (Technicians.user_id = u-tec-07)
  { user_id: "u-tec-07", name: SEED.technicians.find((t) => t.user_id === "u-tec-07")?.name ?? "TEC-07", email: "tec07@demo.arquifusion.local", role: "tecnico", zone: "norte" },
  { user_id: "u-mant-01", name: "Carmen Rojas", email: "mant01@demo.arquifusion.local", role: "mantenimiento", zone: null },
  { user_id: "u-sup-01", name: "Luis Paredes", email: "sup01@demo.arquifusion.local", role: "supervisor", zone: "norte" },
  { user_id: "u-adm-01", name: "Elena Rostova", email: "adm01@demo.arquifusion.local", role: "admin", zone: null },
  { user_id: "u-ger-01", name: "Miguel Salazar", email: "ger01@demo.arquifusion.local", role: "gerencia", zone: null },
] as const;

/**
 * Escenarios de falla, alineados con simulator/scenarios.py (A) y con el diagnóstico de ia-gemini.
 * `vars` = variable -> z-score que deja la anomalía (top_factors).
 */
export interface Scenario {
  key: string;
  label: string;
  severity: Severity;
  specialty: Specialty;
  vars: Record<string, number>;
  cause: string;
  action: string;
  summary: string;
  types?: MachineType[];
}

export const SCENARIOS: Scenario[] = [
  {
    key: "degradacion",
    label: "Degradación térmica progresiva",
    severity: "critical",
    specialty: "motor",
    vars: { temperature_c: 4.1, vibration_mm_s: 3.2, fuel_rate_lph: 2.1 },
    cause: "Desgaste de rodamiento del motor con falla de refrigeración asociada",
    action: "Limitar potencia al 40%, inspeccionar rodamientos y circuito de refrigeración antes del próximo turno",
    summary: "Se reemplazó el kit de rodamientos y se purgó el circuito de refrigeración. Temperatura y vibración volvieron a rango nominal.",
  },
  {
    key: "falla_subita",
    label: "Falla súbita hidráulica",
    severity: "critical",
    specialty: "hidraulica",
    vars: { pressure_bar: -4.6, temperature_c: 2.4, vibration_mm_s: 2.2 },
    cause: "Rotura de manguera hidráulica de alta presión",
    action: "Detener el equipo, aislar el circuito y reemplazar la manguera; revisar nivel de aceite",
    summary: "Se cambió la manguera de alta presión y se repuso aceite hidráulico. Presión estabilizada en el nominal.",
    types: ["excavator", "loader", "bulldozer", "drill"],
  },
  {
    key: "presion",
    label: "Pico de presión hidráulica",
    severity: "high",
    specialty: "hidraulica",
    vars: { pressure_bar: 3.4, temperature_c: 1.9 },
    cause: "Válvula de control hidráulico con apertura irregular",
    action: "Calibrar la válvula de control y revisar sellos del cilindro",
    summary: "Se recalibró la válvula de control y se cambió el kit de sellos. Sin picos en 2 h de prueba.",
    types: ["excavator", "loader", "bulldozer", "drill"],
  },
  {
    key: "combustible",
    label: "Consumo de combustible anómalo",
    severity: "medium",
    specialty: "motor",
    vars: { fuel_rate_lph: 3.1, temperature_c: 1.2 },
    cause: "Inyectores obstruidos y filtro de combustible saturado",
    action: "Reemplazar filtro de combustible y limpiar inyectores en la próxima parada",
    summary: "Se cambió el filtro de combustible y se limpiaron inyectores; consumo −11% frente a la semana previa.",
  },
  {
    key: "electrico",
    label: "Falla eléctrica intermitente",
    severity: "high",
    specialty: "electrica",
    vars: { rpm: -3.2, temperature_c: 1.6 },
    cause: "Alternador con salida irregular que provoca caídas de RPM",
    action: "Medir carga del alternador y revisar conexiones de la ECU",
    summary: "Se reemplazó el alternador y se ajustaron terminales de la ECU. RPM estable.",
  },
  {
    key: "neumaticos",
    label: "Vibración por neumático",
    severity: "medium",
    specialty: "neumaticos",
    vars: { vibration_mm_s: 3.0, speed_kmh: -1.8 },
    cause: "Desbalance o desgaste irregular de neumático trasero",
    action: "Inspeccionar presión y desgaste; rotar o reemplazar el neumático",
    summary: "Se rotaron neumáticos y se corrigió la presión. Vibración en rango nominal.",
    types: ["mining_truck", "loader"],
  },
];

export const SCENARIO_BY_KEY = new Map(SCENARIOS.map((s) => [s.key, s]));

/** Causa común del incidente grupal por zona (RF-12, escenario grupal_zona del simulador). */
export const GROUP_CAUSE = {
  cause: "Combustible contaminado en el punto de abastecimiento de la zona",
  action: "Bloquear el surtidor, tomar muestra de combustible y drenar filtros de las máquinas afectadas",
  summary: "Se drenaron y cambiaron filtros de combustible en las máquinas afectadas y se bloqueó el surtidor hasta el análisis de laboratorio.",
};
