import type { IncidentStatus, MachineStatus, MachineType, Role, Severity, Specialty } from "@/api/types";

export const SEVERITY_LABEL: Record<Severity, string> = {
  info: "Info",
  low: "Baja",
  medium: "Media",
  high: "Alta",
  critical: "Crítica",
};

export const SEVERITY_RANK: Record<Severity, number> = { info: 0, low: 1, medium: 2, high: 3, critical: 4 };

export const STATUS_LABEL: Record<MachineStatus, string> = {
  operational: "Operativa",
  stopped: "Detenida",
  maintenance: "En mantenimiento",
  needs_intervention: "Requiere intervención",
  silent: "Sin señal",
};

export const INCIDENT_STATUS_LABEL: Record<IncidentStatus, string> = {
  detected: "Detectado",
  assigned: "Asignado",
  in_progress: "En atención",
  resolved: "Resuelto",
  closed: "Cerrado",
  abandoned: "Sin atención",
};

export const TYPE_LABEL: Record<MachineType, string> = {
  excavator: "Excavadora",
  mining_truck: "Camión minero",
  loader: "Cargador frontal",
  bulldozer: "Tractor oruga",
  drill: "Perforadora",
};

export const TYPE_ICON: Record<MachineType, string> = {
  excavator: "precision_manufacturing",
  mining_truck: "local_shipping",
  loader: "front_loader",
  bulldozer: "agriculture",
  drill: "hardware",
};

export const ROLE_LABEL: Record<Role, string> = {
  operador: "Operador",
  tecnico: "Técnico de campo",
  mantenimiento: "Jefe de mantenimiento",
  supervisor: "Supervisor de operaciones",
  admin: "Administrador",
  gerencia: "Gerencia",
};

export const SPECIALTY_LABEL: Record<Specialty, string> = {
  motor: "Motor",
  hidraulica: "Hidráulica",
  electrica: "Eléctrica",
  neumaticos: "Neumáticos",
};

export const VARIABLE_LABEL: Record<string, { label: string; unit: string }> = {
  temperature_c: { label: "Temperatura", unit: "°C" },
  vibration_mm_s: { label: "Vibración", unit: "mm/s" },
  pressure_bar: { label: "Presión", unit: "bar" },
  fuel_rate_lph: { label: "Combustible", unit: "L/h" },
  load_pct: { label: "Carga", unit: "%" },
  speed_kmh: { label: "Velocidad", unit: "km/h" },
  rpm: { label: "RPM", unit: "rpm" },
};

export const ZONE_LABEL = (z: string | null | undefined) =>
  !z || z === "*" ? "Todas las zonas" : `Zona ${z.charAt(0).toUpperCase()}${z.slice(1)}`;

const nf1 = new Intl.NumberFormat("es-PE", { maximumFractionDigits: 1 });
const nf0 = new Intl.NumberFormat("es-PE", { maximumFractionDigits: 0 });
const usd = new Intl.NumberFormat("es-PE", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export const fmt1 = (n: number | null | undefined) => (n == null || Number.isNaN(n) ? "—" : nf1.format(n));
export const fmt0 = (n: number | null | undefined) => (n == null || Number.isNaN(n) ? "—" : nf0.format(n));
export const fmtUsd = (n: number | null | undefined) => (n == null ? "—" : usd.format(n));
export const fmtPct = (n: number | null | undefined, digits = 1) =>
  n == null ? "—" : `${n.toFixed(digits)}%`;
export const fmtSigned = (n: number, unit = "%") => `${n > 0 ? "+" : ""}${nf1.format(n)}${unit}`;

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("es-PE", { hour: "2-digit", minute: "2-digit" });
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("es-PE", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  // Las fechas sin hora (YYYY-MM-DD) se muestran tal cual, sin corrimiento por zona horaria.
  const d = iso.length === 10 ? new Date(`${iso}T12:00:00Z`) : new Date(iso);
  return d.toLocaleDateString("es-PE", { day: "2-digit", month: "short", year: "numeric" });
}

export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "nunca";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `hace ${s}s`;
  const m = Math.round(s / 60);
  if (m < 60) return `hace ${m} min`;
  const h = Math.round(m / 60);
  if (h < 48) return `hace ${h} h`;
  return `hace ${Math.round(h / 24)} d`;
}

export function minutesBetween(a: string | null, b: string | null): number | null {
  if (!a || !b) return null;
  return Math.round((new Date(b).getTime() - new Date(a).getTime()) / 60000);
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
}
