import type { Location, Severity, Specialty, Technician } from "@/api/types";
import { etaMinutes } from "./geo";

/**
 * Scoring de técnicos con la fórmula de B4 (scoring-tecnicos): especialidad, ETA (haversine),
 * disponibilidad y carga, ponderados según la severidad. Devuelve el desglose de cada candidato
 * (TRZ-03: se guarda el puntaje de todos los candidatos, no solo del elegido).
 */
export interface Candidate {
  technician_id: string;
  name: string;
  score: number;
  eta_min: number;
  breakdown: { specialty: number; eta: number; availability: number; load: number };
}

const WEIGHTS: Record<Severity, { specialty: number; eta: number; availability: number; load: number }> = {
  critical: { specialty: 0.3, eta: 0.45, availability: 0.15, load: 0.1 },
  high: { specialty: 0.35, eta: 0.35, availability: 0.15, load: 0.15 },
  medium: { specialty: 0.4, eta: 0.25, availability: 0.15, load: 0.2 },
  low: { specialty: 0.4, eta: 0.2, availability: 0.15, load: 0.25 },
  info: { specialty: 0.4, eta: 0.2, availability: 0.15, load: 0.25 },
};

export function scoreTechnicians(
  techs: Technician[],
  target: { location: Location; severity: Severity; specialty?: Specialty | null },
  exclude: string[] = [],
): Candidate[] {
  const w = WEIGHTS[target.severity];
  return techs
    .filter((t) => !exclude.includes(t.technician_id))
    .map((t) => {
      const eta = etaMinutes(t.location, target.location);
      const b = {
        specialty: !target.specialty ? 0.5 : t.specialties.includes(target.specialty) ? 1 : 0,
        eta: Math.max(0, 1 - eta / 45),
        availability: t.available ? 1 : 0,
        load: Math.max(0, 1 - t.current_load / 3),
      };
      const score = w.specialty * b.specialty + w.eta * b.eta + w.availability * b.availability + w.load * b.load;
      return { technician_id: t.technician_id, name: t.name, score: Math.round(score * 100) / 100, eta_min: eta, breakdown: b };
    })
    .sort((a, b) => b.score - a.score || a.eta_min - b.eta_min);
}
