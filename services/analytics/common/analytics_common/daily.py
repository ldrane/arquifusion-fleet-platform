"""Estadísticas diarias por máquina (salida de `sql/daily_machine_stats.sql`) y ventanas de tiempo."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

SQL_DIR = Path(__file__).parent / "sql"


@dataclass(frozen=True)
class DailyStat:
    machine_id: str
    machine_type: str
    day: date
    model: str | None
    zone: str | None
    readings: int
    operating_readings: int
    idle_readings: int
    avg_fuel_lph: float | None
    avg_fuel_lph_operating: float | None
    avg_load_pct: float | None
    avg_rpm: float | None
    avg_temperature_c: float | None
    min_hours: float | None
    max_hours: float | None

    @property
    def hours_operated(self) -> float:
        if self.min_hours is None or self.max_hours is None:
            return 0.0
        return max(0.0, self.max_hours - self.min_hours)

    @property
    def fuel_lph(self) -> float | None:
        return self.avg_fuel_lph_operating if self.avg_fuel_lph_operating is not None else self.avg_fuel_lph


def from_rows(rows: list[dict]) -> list[DailyStat]:
    stats = []
    for r in rows:
        day = r["dt"] if isinstance(r["dt"], date) else date.fromisoformat(str(r["dt"]))
        stats.append(
            DailyStat(
                machine_id=r["machine_id"],
                machine_type=r["machine_type"],
                day=day,
                model=r.get("model"),
                zone=r.get("zone"),
                readings=int(r.get("readings") or 0),
                operating_readings=int(r.get("operating_readings") or 0),
                idle_readings=int(r.get("idle_readings") or 0),
                avg_fuel_lph=r.get("avg_fuel_lph"),
                avg_fuel_lph_operating=r.get("avg_fuel_lph_operating"),
                avg_load_pct=r.get("avg_load_pct"),
                avg_rpm=r.get("avg_rpm"),
                avg_temperature_c=r.get("avg_temperature_c"),
                min_hours=r.get("min_hours"),
                max_hours=r.get("max_hours"),
            )
        )
    return stats


def window(stats: list[DailyStat], today: date, days: int, offset: int = 0) -> list[DailyStat]:
    """Días en (today - offset - days, today - offset]."""
    end = today - timedelta(days=offset)
    start = end - timedelta(days=days)
    return [s for s in stats if start < s.day <= end]


def by_machine(stats: list[DailyStat]) -> dict[str, list[DailyStat]]:
    grouped: dict[str, list[DailyStat]] = defaultdict(list)
    for s in stats:
        grouped[s.machine_id].append(s)
    return grouped


def weighted_avg(stats: list[DailyStat], attr: str, weight: str = "operating_readings") -> float | None:
    """Promedio de `attr` ponderado por `weight`, ignorando días sin dato."""
    pairs = [(getattr(s, attr), getattr(s, weight)) for s in stats if getattr(s, attr) is not None]
    total = sum(w for _, w in pairs)
    if not pairs or total == 0:
        return None
    return sum(v * w for v, w in pairs) / total


def latest(stats: list[DailyStat]) -> DailyStat | None:
    return max(stats, key=lambda s: s.day) if stats else None


def median(values: list[float]) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def linear_slope(points: list[tuple[float, float]]) -> float:
    """Pendiente por mínimos cuadrados de (x, y). 0 si hay menos de 3 puntos."""
    if len(points) < 3:
        return 0.0
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    den = sum((x - mx) ** 2 for x, _ in points)
    return 0.0 if den == 0 else sum((x - mx) * (y - my) for x, y in points) / den
