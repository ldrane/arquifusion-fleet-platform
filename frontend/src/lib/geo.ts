import type { Location } from "@/api/types";

/** Distancia en km (haversine). Es la misma fórmula que usa scoring-tecnicos (B4) para el ETA. */
export function haversineKm(a: Location, b: Location): number {
  const R = 6371;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

/** ETA en minutos a velocidad de camioneta dentro de la mina (25 km/h) + 2 min de preparación. */
export function etaMinutes(a: Location, b: Location, speedKmh = 25): number {
  return Math.max(1, Math.round((haversineKm(a, b) / speedKmh) * 60 + 2));
}
