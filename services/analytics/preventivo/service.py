"""Mantenimiento preventivo basado en condición (RF-03.1, RF-03.2, RF-03.3).

La próxima fecha de cada máquina depende de las horas reales desde el último mantenimiento, ajustadas por
la intensidad de uso (carga y temperatura) y por el health score. Se compara con el calendario fijo tradicional
para marcar mantenimientos atrasados (`overdue`) e innecesarios (`unnecessary`).
Salida: `insights` `maintenance_plan` (forma de GET /v1/maintenance/plan) y `next_maintenance_at` en `machines`.

El intervalo sale de `catalog MODEL#<model>.maintenance_interval_h` (#13) y el calendario fijo usa las 16 h/día
del seed. Solo se actualizan máquinas existentes (`attribute_exists(pk)`, nunca se crean, contratos.md §9).
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

from analytics_common import daily, fleet, records
from analytics_common.athena import fetch_rows
from analytics_common.dynamo import key_of, scan_all
from analytics_common.insights_store import write_insight
from analytics_common.run_context import RunContext
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

INTENSITY_WINDOW_DAYS = 30
OVERDUE_HEALTH = 40
HEALTH_ADJUST_BELOW = 60
UNNECESSARY_CALENDAR_DAYS = 14  # el calendario la pide en ≤ 14 días…
UNNECESSARY_MIN_DAYS = 30  # …pero la condición permite esperar > 30 días
MIN_DAILY_HOURS = 0.5
DEFAULT_DAILY_HOURS = 12.0


@dataclass(frozen=True)
class PlanItem:
    machine_id: str
    zone: str | None
    next_maintenance_at: date
    days_to_next: float
    health_score: float
    flag: str
    reason: str


def intensity(stats: list[daily.DailyStat]) -> float:
    """Factor ≥ 1: carga sobre 70 % y temperatura sobre 90 °C desgastan más rápido."""
    load = daily.weighted_avg(stats, "avg_load_pct") or 0.0
    temp = daily.weighted_avg(stats, "avg_temperature_c", weight="readings") or 0.0
    factor = 1 + 0.5 * max(0.0, (load - 70) / 30) + 0.3 * max(0.0, (temp - 90) / 20)
    return round(min(factor, 2.0), 2)


def plan_machine(
    machine: dict,
    stats: list[daily.DailyStat],
    last: records.Record | None,
    today: date,
    catalog: fleet.Catalog | None = None,
) -> PlanItem:
    machine_type = machine.get("type") or (stats[0].machine_type if stats else None)
    model = machine.get("model") or (stats[0].model if stats else None)
    interval = (catalog or fleet.Catalog()).service_interval(model, machine_type)
    recent = daily.window(stats, today, INTENSITY_WINDOW_DAYS)
    newest = daily.latest(stats)
    hours_now = float(
        newest.max_hours if newest and newest.max_hours is not None else machine.get("operating_hours") or 0
    )
    if last and last.operating_hours is not None:
        hours_since = max(0.0, hours_now - last.operating_hours)
    else:
        hours_since = hours_now % interval  # sin registro: se asume el último servicio en el múltiplo anterior
    last_day = last.day if last else _date(machine.get("last_maintenance_at")) or today - timedelta(days=30)

    factor = intensity(recent)
    used = hours_since * factor
    remaining = interval - used
    health = float(machine.get("health_score", 100))
    if health < HEALTH_ADJUST_BELOW and remaining > 0:
        remaining *= health / HEALTH_ADJUST_BELOW
    daily_hours = sum(s.hours_operated for s in recent) / INTENSITY_WINDOW_DAYS if recent else DEFAULT_DAILY_HOURS
    days_to_next = max(0.0, remaining) / (max(daily_hours, MIN_DAILY_HOURS) * factor)
    next_at = today + timedelta(days=math.ceil(days_to_next))
    calendar_due = last_day + timedelta(days=round(interval / fleet.NOMINAL_HOURS_PER_DAY))

    if remaining <= 0 or health < OVERDUE_HEALTH:
        flag = "overdue"
        reason = (
            f"Health score {health:.0f} bajo el umbral {OVERDUE_HEALTH}"
            if health < OVERDUE_HEALTH
            else f"Superó el intervalo: {used:.0f} h efectivas de {interval:.0f} (intensidad {factor:.2f})"
        )
    elif calendar_due <= today + timedelta(days=UNNECESSARY_CALENDAR_DAYS) and days_to_next > UNNECESSARY_MIN_DAYS:
        flag = "unnecessary"
        reason = (
            f"El calendario fijo lo programa el {calendar_due.isoformat()}, "
            f"pero la condición permite esperar {days_to_next:.0f} días"
        )
    else:
        flag = "on_track"
        reason = f"{max(remaining, 0):.0f} h efectivas restantes a {daily_hours:.1f} h/día (intensidad {factor:.2f})"
    zone = machine.get("zone") or (machine.get("location") or {}).get("zone") or (newest.zone if newest else None)
    return PlanItem(machine["machine_id"], zone, next_at, days_to_next, health, flag, reason)


def _date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def build_plan(
    machines: list[dict],
    stats: list[daily.DailyStat],
    recs: list[records.Record],
    today: date,
    catalog: fleet.Catalog | None = None,
) -> list[dict]:
    """Plan priorizado: atrasadas primero, luego por días restantes y health score."""
    by_machine = daily.by_machine(stats)
    last_by_machine: dict[str, records.Record] = {}
    for rec in sorted(recs, key=lambda r: r.day):
        if rec.kind == "preventivo":
            last_by_machine[rec.machine_id] = rec
    known = {m["machine_id"] for m in machines}
    machines = machines + [
        {"machine_id": mid, "type": s[0].machine_type} for mid, s in by_machine.items() if mid not in known
    ]
    items = [
        plan_machine(m, by_machine.get(m["machine_id"], []), last_by_machine.get(m["machine_id"]), today, catalog)
        for m in machines
    ]
    items.sort(key=lambda i: (i.flag != "overdue", i.days_to_next, i.health_score))
    return [
        {
            "machine_id": i.machine_id,
            "zone": i.zone,
            "next_maintenance_at": i.next_maintenance_at.isoformat(),
            "priority": rank,
            "flag": i.flag,
            "reason": i.reason,
        }
        for rank, i in enumerate(items, start=1)
    ]


def run(ctx: RunContext, athena, machines_table, records_table, insights_table, catalog_table=None) -> dict:
    stats = daily.from_rows(fetch_rows(athena, ctx.query_execution_id))
    machines_raw = scan_all(machines_table, FilterExpression=Attr("machine_id").exists())
    catalog = fleet.load_catalog(catalog_table) if catalog_table is not None else fleet.Catalog()
    plan = build_plan(machines_raw, stats, records.normalize(scan_all(records_table)), ctx.today, catalog)
    write_insight(insights_table, "maintenance_plan", plan, ctx.run_at_iso, ctx.correlation_id)

    next_by_machine = {p["machine_id"]: p["next_maintenance_at"] for p in plan}
    for machine in machines_raw:
        machine_table_update(machines_table, machine, next_by_machine[machine["machine_id"]])
    flags = [p["flag"] for p in plan]
    return {
        "kind": "maintenance_plan",
        "machines": len(plan),
        "overdue": flags.count("overdue"),
        "unnecessary": flags.count("unnecessary"),
    }


def machine_table_update(table, machine: dict, next_at: str) -> None:
    """Actualiza solo `next_maintenance_at` (RF-03.3); el resto del ítem es de procesar y de B."""
    key = key_of(table, machine)
    try:
        table.update_item(
            Key=key,
            UpdateExpression="SET next_maintenance_at = :n",
            ConditionExpression=f"attribute_exists({next(iter(key))})",
            ExpressionAttributeValues={":n": next_at},
        )
    except ClientError as exc:  # la máquina se borró entre el scan y la escritura: no se recrea
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
