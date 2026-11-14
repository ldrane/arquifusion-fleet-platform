"""Productividad de la flota (RF-08.1, RF-08.2, RF-08.3, RF-08.4).

Utilización = lecturas en operación / lecturas totales. Clasifica subutilizadas y sobreexplotadas, calcula el
costo por hora (combustible + mantenimiento) y ubica cada máquina en la matriz productividad × costo frente a
la mediana de su tipo. Sugiere redistribuir entre zonas máquinas del mismo tipo.
Salida: `insights` `productivity#7d` y `productivity#30d` (forma de GET /v1/analytics/productivity).
"""

from dataclasses import dataclass
from datetime import date, timedelta

from analytics_common import daily, fleet, records
from analytics_common.athena import fetch_rows
from analytics_common.dynamo import scan_all
from analytics_common.insights_store import write_insight
from analytics_common.run_context import RunContext

PERIODS = {"7d": 7, "30d": 30}
UNDERUSED_PCT = 40.0
OVERUSED_PCT = 85.0
OVERUSED_HOURS_PER_DAY = 18.0


@dataclass(frozen=True)
class MachineUse:
    machine_id: str
    machine_type: str
    zone: str | None
    utilization_pct: float
    hours_per_day: float
    productivity: float  # utilización × carga media: índice comparable dentro del tipo
    cost_per_hour_usd: float

    @property
    def classification(self) -> str:
        if self.utilization_pct >= OVERUSED_PCT or self.hours_per_day >= OVERUSED_HOURS_PER_DAY:
            return "overused"
        if self.utilization_pct < UNDERUSED_PCT:
            return "underused"
        return "normal"


def measure(mid: str, stats: list[daily.DailyStat], recs: list[records.Record], period_days: int) -> MachineUse:
    readings = sum(s.readings for s in stats) or 1
    utilization = sum(s.operating_readings for s in stats) / readings * 100
    hours = sum(s.hours_operated for s in stats)
    load = daily.weighted_avg(stats, "avg_load_pct") or 0.0
    fuel_cost = (daily.weighted_avg(stats, "fuel_lph") or 0.0) * fleet.FUEL_PRICE_USD_PER_L
    maintenance_cost = sum(r.cost_usd for r in recs) / hours if hours else 0.0
    return MachineUse(
        machine_id=mid,
        machine_type=stats[0].machine_type,
        zone=stats[-1].zone,
        utilization_pct=round(utilization, 1),
        hours_per_day=hours / period_days,
        productivity=utilization * load / 100,
        cost_per_hour_usd=round(fuel_cost + maintenance_cost, 2),
    )


def _quadrant(use: MachineUse, prod_median: float, cost_median: float) -> str:
    prod = "high_prod" if use.productivity >= prod_median else "low_prod"
    cost = "high_cost" if use.cost_per_hour_usd >= cost_median else "low_cost"
    return f"{prod}_{cost}"


def _suggestion(use: MachineUse, peers: list[MachineUse]) -> str | None:
    """Sugiere mover capacidad entre zonas dentro del mismo tipo de máquina."""
    if use.classification == "underused":
        target = next((p for p in peers if p.classification == "overused" and p.zone != use.zone), None)
        if target:
            return f"Trasladar a la zona {target.zone} para apoyar a {target.machine_id} (sobreexplotada)"
    if use.classification == "overused":
        helper = next((p for p in peers if p.classification == "underused" and p.zone != use.zone), None)
        if helper:
            return f"Redistribuir carga con {helper.machine_id} (zona {helper.zone}, subutilizada)"
    return None


def analyze(stats: list[daily.DailyStat], recs: list[records.Record], today: date, period_days: int) -> list[dict]:
    since = today - timedelta(days=period_days)
    recs_by_machine: dict[str, list[records.Record]] = {}
    for r in recs:
        if since < r.day <= today:
            recs_by_machine.setdefault(r.machine_id, []).append(r)
    uses = [
        measure(mid, s, recs_by_machine.get(mid, []), period_days)
        for mid, s in daily.by_machine(daily.window(stats, today, period_days)).items()
    ]
    rows = []
    for use in uses:
        peers = [u for u in uses if u.machine_type == use.machine_type]
        prod_median = daily.median([p.productivity for p in peers]) or 0.0
        cost_median = daily.median([p.cost_per_hour_usd for p in peers]) or 0.0
        rows.append(
            {
                "machine_id": use.machine_id,
                "zone": use.zone,
                "utilization_pct": use.utilization_pct,
                "classification": use.classification,
                "cost_per_hour_usd": use.cost_per_hour_usd,
                "quadrant": _quadrant(use, prod_median, cost_median),
                "redistribution_suggestion": _suggestion(use, [p for p in peers if p is not use]),
            }
        )
    rows.sort(key=lambda r: r["utilization_pct"])
    return rows


def run(ctx: RunContext, athena, records_table, insights_table) -> dict:
    stats = daily.from_rows(fetch_rows(athena, ctx.query_execution_id))
    recs = records.normalize(scan_all(records_table))
    summary = {}
    for period, days in PERIODS.items():
        rows = analyze(stats, recs, ctx.today, days)
        write_insight(insights_table, f"productivity#{period}", rows, ctx.run_at_iso, ctx.correlation_id)
        if period == "7d":
            classes = [r["classification"] for r in rows]
            summary = {"underused_7d": classes.count("underused"), "overused_7d": classes.count("overused")}
    return {"kind": "productivity", **summary}
