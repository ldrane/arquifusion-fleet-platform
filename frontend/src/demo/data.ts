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
import type { Location, MachineStatus, MachineType, Severity, Specialty } from "@/api/types";

export interface SeedMachine {
  machine_id: string;
  operation_id: string;
  model: string;
  type: MachineType;
  zone: string;
  location: Location;
  home_location: Location;
  /** seed v4: estado inicial (operational | maintenance | stopped). El simulador (A) lo respeta. */
  status?: MachineStatus;
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
  { user_id: "u-tec-07", name: SEED.technicians.find((t) => t.user_id === "u-tec-07")?.name ?? "TEC-07", email: "tec07@demo.arquifusion.local", role: "tecnico", zone: "norte", technician_id: "TEC-07" },
  { user_id: "u-mant-01", name: "Carmen Rojas", email: "mant01@demo.arquifusion.local", role: "mantenimiento", zone: null },
  { user_id: "u-sup-01", name: "Luis Paredes", email: "sup01@demo.arquifusion.local", role: "supervisor", zone: "norte" },
  { user_id: "u-adm-01", name: "Elena Rostova", email: "adm01@demo.arquifusion.local", role: "admin", zone: null },
  { user_id: "u-ger-01", name: "Miguel Salazar", email: "ger01@demo.arquifusion.local", role: "gerencia", zone: null },
] as const;

/**
 * Patrones de falla del modo demo.
 * - `simulator: true`: MISMO nombre y efecto que `simulator/scenarios.py` (A): `degradacion`, `falla_subita`,
 *   `combustible` (+ `grupal_zona`, ver GROUP_CAUSE). Son los únicos que se pueden inyectar desde el panel
 *   "Simulador", que equivale a `python -m simulator stream --scenario <key>` (#27).
 * - `simulator: false`: patrones de fondo para que el historial y el piloto automático muestren las 4 especialidades
 *   (hidráulica, eléctrica, neumáticos). No existen en el simulador y no llevan `sim_scenario` en la telemetría.
 * `vars` = variable -> z-score que deja la anomalía (top_factors, máx. 3). `specialty` sigue la regla de
 * contratos.md §8.2 (variable dominante -> especialidad) salvo que el repuesto sugerido diga otra cosa.
 */
export interface Scenario {
  key: string;
  label: string;
  simulator: boolean;
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
    label: "Degradación progresiva (temperatura, vibración, combustible)",
    simulator: true,
    // Golden path (contratos.md §8.3): EX-023 high/motor -> TEC-07 (0.98), 2.º TEC-01
    severity: "high",
    specialty: "motor",
    vars: { temperature_c: 4.1, vibration_mm_s: 3.2, fuel_rate_lph: 2.1 },
    cause: "Desgaste de rodamiento del motor con falla de refrigeración asociada",
    action: "Limitar potencia al 40%, inspeccionar rodamientos y circuito de refrigeración antes del próximo turno",
    summary: "Se reemplazó el kit de rodamientos y se purgó el circuito de refrigeración. Temperatura y vibración volvieron a rango nominal.",
  },
  {
    key: "falla_subita",
    label: "Falla súbita (salto de temperatura y vibración, caída de presión)",
    simulator: true,
    severity: "critical",
    specialty: "motor",
    // simulator: temperatura +40 °C, vibración x3.5, presión x0.55
    vars: { temperature_c: 4.8, vibration_mm_s: 4.2, pressure_bar: -3.9 },
    cause: "Sobrecalentamiento súbito del motor con pérdida de presión de aceite (falla de bomba de lubricación)",
    action: "Detener el equipo de inmediato, revisar bomba y nivel de aceite y el estado de los rodamientos",
    summary: "Se reemplazó la bomba de aceite y se cambió el aceite contaminado. Temperatura y presión volvieron al nominal.",
  },
  {
    key: "presion",
    label: "Pico de presión hidráulica",
    simulator: false,
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
    label: "Consumo de combustible anómalo con carga normal",
    simulator: true,
    severity: "medium",
    specialty: "motor",
    // simulator: combustible x1.5 progresivo, sin otras variables
    vars: { fuel_rate_lph: 3.4 },
    cause: "Inyectores obstruidos y filtro de combustible saturado",
    action: "Reemplazar filtro de combustible y limpiar inyectores en la próxima parada",
    summary: "Se cambió el filtro de combustible y se limpiaron inyectores; consumo −11% frente a la semana previa.",
  },
  {
    key: "electrico",
    label: "Falla eléctrica intermitente",
    simulator: false,
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
    simulator: false,
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
/** Escenarios inyectables = los de `simulator/scenarios.py` (sin `normal` ni `ociosa`, que no abren incidentes). */
export const SIMULATOR_SCENARIOS = SCENARIOS.filter((s) => s.simulator);
/** Máquina por defecto de cada escenario en el smoke/pitch (scripts/smoke_golden_path.sh usa EX-023). */
export const DEMO_MACHINE = "EX-023";

/** Causa común del incidente grupal por zona (RF-12, escenario grupal_zona del simulador). */
export const GROUP_CAUSE = {
  cause: "Combustible contaminado en el punto de abastecimiento de la zona",
  action: "Bloquear el surtidor, tomar muestra de combustible y drenar filtros de las máquinas afectadas",
  summary: "Se drenaron y cambiaron filtros de combustible en las máquinas afectadas y se bloqueó el surtidor hasta el análisis de laboratorio.",
};
