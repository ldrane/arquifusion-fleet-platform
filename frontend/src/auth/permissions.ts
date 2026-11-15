import type { Role } from "@/api/types";

/**
 * RBAC del front = `x-roles` de cada operación de openapi.yaml.
 * El front solo oculta lo que el rol no puede usar; la autorización real la hace la Lambda.
 */
const ALL: Role[] = ["operador", "tecnico", "mantenimiento", "supervisor", "admin", "gerencia"];

export const CAN = {
  machines: ALL,
  telemetry: ["tecnico", "mantenimiento", "supervisor", "admin", "gerencia"],
  timeline: ["tecnico", "mantenimiento", "supervisor", "admin", "gerencia"],
  incidents: ALL,
  ack: ["tecnico", "mantenimiento"],
  resolve: ["tecnico", "mantenimiento"],
  assign: ["mantenimiento", "supervisor", "admin"],
  technicians: ["mantenimiento", "supervisor", "admin"],
  myStatus: ["tecnico"],
  inventory: ["mantenimiento", "supervisor", "admin"],
  partsRanking: ["mantenimiento", "supervisor", "admin"],
  partsForecast: ["mantenimiento", "admin"],
  maintenancePlan: ["mantenimiento", "supervisor", "admin"],
  fuel: ["supervisor", "admin", "gerencia"],
  productivity: ["supervisor", "admin", "gerencia"],
  kpis: ["supervisor", "admin", "gerencia"],
  precursors: ["mantenimiento", "supervisor", "admin", "gerencia"],
  report: ["admin", "gerencia", "supervisor"],
  mlModel: ["admin", "mantenimiento"],
  retrain: ["admin"],
  simulate: ["admin", "mantenimiento"],
  pulse: ALL,
  assistant: ["tecnico", "mantenimiento", "supervisor", "admin", "gerencia"],
  // Firestore (infra/gcp/firestore.rules): quién escribe en el chat del incidente.
  // El operador también participa del canal (docs/requerimientos.md §2).
  chatWrite: ["operador", "tecnico", "mantenimiento", "supervisor"],
} satisfies Record<string, Role[]>;

export type Capability = keyof typeof CAN;

export function can(role: Role | null | undefined, cap: Capability): boolean {
  return !!role && (CAN[cap] as Role[]).includes(role);
}

/** Navegación principal (mismo orden que el diseño). `cap` = permiso mínimo para ver la vista. */
export interface NavItem {
  path: string;
  label: string;
  icon: string;
  caps: Capability[]; // basta con uno
}

export const NAV: NavItem[] = [
  { path: "/", label: "Centro de Mando", icon: "radar", caps: ["machines"] },
  { path: "/salud", label: "Salud Predictiva", icon: "vital_signs", caps: ["machines"] },
  { path: "/despacho", label: "Despacho y Técnicos", icon: "engineering", caps: ["technicians", "myStatus"] },
  { path: "/inventario", label: "Inventario y Repuestos", icon: "inventory_2", caps: ["inventory"] },
  { path: "/eficiencia", label: "Eficiencia y Combustible", icon: "local_gas_station", caps: ["fuel"] },
  { path: "/incidentes", label: "Historial de Incidentes", icon: "history_toggle_off", caps: ["incidents"] },
  { path: "/asistente", label: "Arqui · Asistente IA", icon: "arqui", caps: ["assistant"] }, // icon "arqui" = mascota SVG
];

export function navFor(role: Role | null | undefined): NavItem[] {
  return NAV.filter((n) => n.caps.some((c) => can(role, c)));
}
