"""Gestión de repuestos (RF-04.1, RF-04.2, RF-04.3, RF-04.4, RF-04.5, RF-04.6).

- Ranking: unidades consumidas en 90 días por componente y consumo irregular (variabilidad semanal alta).
- Pronóstico por almacén y horizonte (7/30/90 días) = consumo histórico repartido según las máquinas activas
  de las zonas que atiende cada almacén + demanda planificada de máquinas con mantenimiento próximo o health bajo,
  usando la mezcla de componentes que históricamente consume cada tipo de máquina.
- Stock mínimo = demanda en el lead time + stock de seguridad (95 %). Máximo = mínimo + 30 días de demanda.
Salida: `insights` `parts_ranking` y `parts_forecast#{7,30,90}` (forma de GET /v1/parts/*).
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from analytics_common import daily, fleet, records
from analytics_common.athena import fetch_rows
from analytics_common.dynamo import scan_all
from analytics_common.insights_store import write_insight
from analytics_common.run_context import RunContext
from boto3.dynamodb.conditions import Attr

HISTORY_DAYS = 90
WEEKS = 13
HORIZONS = (7, 30, 90)
ACTIVE_WINDOW_DAYS = 7
SAFETY_Z = 1.65
DEFAULT_LEAD_TIME_DAYS = 7
MAX_COVER_DAYS = 30
IRREGULAR_CV = 1.5
IRREGULAR_PEAK_SHARE = 0.5
IRREGULAR_MIN_UNITS = 3


@dataclass
class Demand:
    """Consumo histórico de un componente."""

    units_90d: int = 0
    weekly: list[int] = field(default_factory=lambda: [0] * WEEKS)

    @property
    def daily_rate(self) -> float:
        return self.units_90d / HISTORY_DAYS

    @property
    def daily_std(self) -> float:
        mean = sum(self.weekly) / WEEKS
        variance = sum((w - mean) ** 2 for w in self.weekly) / WEEKS
        return math.sqrt(variance) / math.sqrt(7)

    @property
    def irregular(self) -> bool:
        if self.units_90d < IRREGULAR_MIN_UNITS:
            return False
        mean = self.units_90d / WEEKS
        cv = (self.daily_std * math.sqrt(7)) / mean if mean else 0.0
        return cv >= IRREGULAR_CV or max(self.weekly) / self.units_90d >= IRREGULAR_PEAK_SHARE


def demand_history(recs: list[records.Record], today: date) -> dict[str, Demand]:
    out: dict[str, Demand] = defaultdict(Demand)
    for r in recs:
        age = (today - r.day).days
        if not 0 <= age < HISTORY_DAYS:
            continue
        week = min(age // 7, WEEKS - 1)
        for component, qty in r.components.items():
            out[component].units_90d += qty
            out[component].weekly[week] += qty
    return out


def component_mix(recs: list[records.Record], machine_type: dict[str, str]) -> dict[str, dict[str, float]]:
    """Unidades esperadas de cada componente por intervención, según el tipo de máquina."""
    totals: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    interventions: dict[str, int] = defaultdict(int)
    for r in recs:
        mtype = machine_type.get(r.machine_id)
        if not mtype:
            continue
        interventions[mtype] += 1
        for component, qty in r.components.items():
            totals[mtype][component] += qty
    return {t: {c: q / interventions[t] for c, q in comps.items()} for t, comps in totals.items()}


def ranking(history: dict[str, Demand], names: dict[str, str]) -> list[dict]:
    rows = [
        {
            "component_id": cid,
            "name": names.get(cid, cid),
            "units_used_90d": d.units_90d,
            "irregular_consumption": d.irregular,
        }
        for cid, d in history.items()
        if d.units_90d > 0
    ]
    return sorted(rows, key=lambda r: r["units_used_90d"], reverse=True)


def warehouse_shares(inventory: list[dict], active_by_zone: dict[str, int]) -> dict[str, dict[str, float]]:
    """Fracción de la flota que atiende cada almacén. Sin zona declarada, se reparte en partes iguales."""
    warehouses = sorted({i["location_id"] for i in inventory})
    zones_of = {w: {i["zone"] for i in inventory if i["location_id"] == w and i.get("zone")} for w in warehouses}
    total = sum(active_by_zone.values())
    shares = {}
    for w in warehouses:
        if zones_of[w] and total:
            shares[w] = sum(active_by_zone.get(z, 0) for z in zones_of[w]) / total
        else:
            shares[w] = 1 / len(warehouses)
    return {"share": shares, "zones": zones_of}


def forecast(
    horizon: int,
    history: dict[str, Demand],
    mix: dict[str, dict[str, float]],
    machines: list[dict],
    inventory: list[dict],
    catalog: dict[str, dict],
    active_by_zone: dict[str, int],
    today: date,
) -> list[dict]:
    layout = warehouse_shares(inventory, active_by_zone)
    shares, zones_of = layout["share"], layout["zones"]
    if not shares:
        return []
    default_wh = max(shares, key=shares.get)
    stock = {(i["location_id"], i["component_id"]): int(i.get("stock", 0)) for i in inventory}

    planned: dict[tuple[str, str], float] = defaultdict(float)
    limit = today + timedelta(days=horizon)
    for m in machines:
        due = str(m.get("next_maintenance_at") or "")[:10]
        at_risk = float(m.get("health_score", 100)) < fleet.AT_RISK_HEALTH
        if not (at_risk or (due and due <= limit.isoformat())):
            continue
        zone = m.get("zone") or (m.get("location") or {}).get("zone")
        warehouse = next((w for w, zs in zones_of.items() if zone in zs), default_wh)
        for component, qty in mix.get(m.get("type", ""), {}).items():
            planned[(warehouse, component)] += qty

    keys = set(stock) | set(planned) | {(w, c) for w in shares for c, d in history.items() if d.units_90d}
    rows = []
    for warehouse, component in sorted(keys):
        demand = history.get(component, Demand())
        share = shares.get(warehouse, 0.0)
        rate, std = demand.daily_rate * share, demand.daily_std * share
        lead = float(catalog.get(component, {}).get("lead_time_days", DEFAULT_LEAD_TIME_DAYS))
        rec_min = math.ceil(rate * lead + SAFETY_Z * std * math.sqrt(lead))
        rec_max = max(rec_min + 1, rec_min + math.ceil(rate * MAX_COVER_DAYS))
        planned_units = planned.get((warehouse, component), 0.0)
        rows.append(
            {
                "warehouse_id": warehouse,
                "component_id": component,
                "expected_demand": round(rate * horizon + planned_units, 2),
                "stock": stock.get((warehouse, component), 0),
                "recommended_min": rec_min,
                "recommended_max": rec_max,
                "shortage_for_planned_maintenance": stock.get((warehouse, component), 0) < math.ceil(planned_units),
            }
        )
    return rows


def active_machines_by_zone(stats: list[daily.DailyStat], machines: list[dict], today: date) -> dict[str, int]:
    recent = daily.by_machine(daily.window(stats, today, ACTIVE_WINDOW_DAYS))
    counts: dict[str, int] = defaultdict(int)
    if recent:
        for rows in recent.values():
            counts[rows[-1].zone or "sin_zona"] += 1
    else:
        for m in machines:
            counts[m.get("zone") or "sin_zona"] += 1
    return dict(counts)


def _catalog(items: list[dict]) -> dict[str, dict]:
    """Solo ítems de componente (no de compatibilidad), con alias de nombre y lead time."""
    out = {}
    for item in items:
        cid = item.get("component_id")
        if not cid or str(item.get("sk", "")).startswith("COMPAT#"):
            continue
        lead = item.get("lead_time_days", item.get("lead_time"))
        out[cid] = {
            "name": item.get("name") or item.get("nombre") or cid,
            "lead_time_days": lead if lead is not None else DEFAULT_LEAD_TIME_DAYS,
        }
    return out


def run(ctx: RunContext, athena, machines_table, records_table, inventory_table, catalog_table, insights_table) -> dict:
    stats = daily.from_rows(fetch_rows(athena, ctx.query_execution_id))
    machines = scan_all(machines_table, FilterExpression=Attr("machine_id").exists())
    recs = records.normalize(scan_all(records_table))
    inventory = [i for i in scan_all(inventory_table) if i.get("location_id") and i.get("component_id")]
    catalog = _catalog(scan_all(catalog_table))

    machine_type = {m["machine_id"]: m.get("type") for m in machines if m.get("type")}
    machine_type.update({s.machine_id: s.machine_type for s in stats})
    history = demand_history(recs, ctx.today)
    write_insight(
        insights_table,
        "parts_ranking",
        ranking(history, {c: v["name"] for c, v in catalog.items()}),
        ctx.run_at_iso,
        ctx.correlation_id,
    )
    mix = component_mix(recs, machine_type)
    active = active_machines_by_zone(stats, machines, ctx.today)
    shortages = 0
    for horizon in HORIZONS:
        rows = forecast(horizon, history, mix, machines, inventory, catalog, active, ctx.today)
        write_insight(insights_table, f"parts_forecast#{horizon}", rows, ctx.run_at_iso, ctx.correlation_id)
        if horizon == 30:
            shortages = sum(r["shortage_for_planned_maintenance"] for r in rows)
    return {"kind": "parts", "shortages_30d": shortages}
