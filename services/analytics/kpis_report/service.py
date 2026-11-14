"""KPIs de la flota y resumen ejecutivo diario (RF-10.3, RF-11.4, RF-13.3).

Cierra `AnalisisDiario`: calcula disponibilidad, MTBF, MTTR, incidentes abiertos, máquinas en riesgo,
utilización y costo de combustible por tonelada para 7 y 30 días, y pide a `ia-gemini` (task
`executive_report`) el resumen para gerencia. Si `ia-gemini` falla, usa un resumen determinista.
Salida: `insights` `kpis#7d`, `kpis#30d` (GET /v1/analytics/kpis) y `report#daily` (GET /v1/reports/latest).
Los KPIs se escriben para toda la flota (`sk=LATEST`) y por zona (`sk=LATEST#<zone>`, contratos.md §9.1), así
`GET /v1/analytics/kpis?zone=norte` tiene su ítem. Las toneladas usan `payload_t` del catálogo `MODEL#…` (#13).
"""

import json
from datetime import date, datetime, timedelta

from analytics_common import daily, fleet
from analytics_common.athena import fetch_rows
from analytics_common.dynamo import scan_all
from analytics_common.insights_store import write_insight
from analytics_common.run_context import RunContext
from arquifusion_shared.observability import logger
from boto3.dynamodb.conditions import Attr

PERIODS = {"7d": 7, "30d": 30}
OPEN_STATUSES = {"detected", "assigned", "in_progress"}
FALLBACK_PROMPT_VERSION = "kpis-report-fallback-v1"


def _ts(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def kpis(
    stats: list[daily.DailyStat],
    incidents: list[dict],
    machines: list[dict],
    today: date,
    days: int,
    catalog: fleet.Catalog | None = None,
) -> dict:
    """KPIs de un periodo. MTBF sin fallas en el periodo = horas operadas totales (cota inferior)."""
    catalog = catalog or fleet.Catalog()
    period = daily.window(stats, today, days)
    since = today - timedelta(days=days)
    detected = [i for i in incidents if (t := _ts(i.get("detected_at"))) and since < t.date() <= today]
    resolved = [i for i in incidents if (t := _ts(i.get("resolved_at"))) and since < t.date() <= today]

    repair_hours = [
        (_ts(i["resolved_at"]) - _ts(i["detected_at"])).total_seconds() / 3600
        for i in resolved
        if _ts(i.get("detected_at"))
    ]
    downtime_h = sum(
        (i["downtime_minutes"] / 60) if i.get("downtime_minutes") is not None else h
        for i, h in zip(resolved, repair_hours, strict=False)
    )
    fleet_size = len({m["machine_id"] for m in machines} | {s.machine_id for s in period}) or 1
    hours_operated = sum(s.hours_operated for s in period)
    readings = sum(s.readings for s in period)
    fuel_l = sum((s.fuel_lph or 0.0) * s.hours_operated for s in period)
    tons = sum(
        (s.avg_load_pct or 0.0) / 100 * catalog.capacity_tph(s.model, s.machine_type) * s.hours_operated
        for s in period
    )
    return {
        "availability_pct": round(max(0.0, 100 * (1 - downtime_h / (fleet_size * days * 24))), 2),
        "mtbf_hours": round(hours_operated / len(detected) if detected else hours_operated, 1),
        "mttr_hours": round(sum(repair_hours) / len(repair_hours), 2) if repair_hours else 0.0,
        "open_incidents": sum(1 for i in incidents if i.get("status") in OPEN_STATUSES),
        "machines_at_risk": sum(
            1
            for m in machines
            if m.get("health_score", 100) < fleet.AT_RISK_HEALTH or m.get("status") == "needs_intervention"
        ),
        "fleet_utilization_pct": round(sum(s.operating_readings for s in period) / readings * 100, 1)
        if readings
        else 0.0,
        "fuel_cost_per_ton_usd": round(fuel_l * fleet.FUEL_PRICE_USD_PER_L / tons, 3) if tons else 0.0,
    }


def fallback_summary(figures: dict) -> str:
    k = figures["kpis_7d"]
    return (
        f"Últimos 7 días: disponibilidad {k['availability_pct']:.1f}%, MTTR {k['mttr_hours']:.1f} h, "
        f"{k['open_incidents']} incidentes abiertos y {k['machines_at_risk']} máquinas en riesgo. "
        f"Combustible {k['fuel_cost_per_ton_usd']:.2f} USD/t."
    )


def executive_report(figures: dict, invoke_ia, correlation_id: str) -> tuple[str, str]:
    """Pide el resumen a `ia-gemini`; nunca falla (RF-10.3, MH-MC-03)."""
    try:
        out = invoke_ia({"task": "executive_report", "correlation_id": correlation_id, "payload": {"figures": figures}})
        return out["result"]["summary_text"], out["prompt_version"]
    except Exception as exc:  # la Lambda de IA no debe tumbar el reporte
        logger.warning("ia-gemini no disponible para el reporte", extra={"error": str(exc)})
        return fallback_summary(figures), FALLBACK_PROMPT_VERSION


def lambda_invoker(lambda_client, function_name: str):
    def invoke(payload: dict) -> dict:
        resp = lambda_client.invoke(FunctionName=function_name, Payload=json.dumps(payload).encode())
        if resp.get("FunctionError"):
            raise RuntimeError(f"ia-gemini respondió con error: {resp['FunctionError']}")
        return json.loads(resp["Payload"].read())

    return invoke


def _zone_of(item: dict) -> str | None:
    return item.get("zone") or (item.get("location") or {}).get("zone")


def zones(machines: list[dict], stats: list[daily.DailyStat]) -> list[str]:
    return sorted({z for z in (_zone_of(m) for m in machines) if z} | {s.zone for s in stats if s.zone})


def kpis_by_zone(
    stats: list[daily.DailyStat],
    incidents: list[dict],
    machines: list[dict],
    today: date,
    days: int,
    catalog: fleet.Catalog | None = None,
) -> dict[str, dict]:
    """KPIs de cada zona con las máquinas, lecturas e incidentes de esa zona."""
    return {
        zone: kpis(
            [s for s in stats if s.zone == zone],
            [i for i in incidents if i.get("zone") == zone],
            [m for m in machines if _zone_of(m) == zone],
            today,
            days,
            catalog,
        )
        for zone in zones(machines, stats)
    }


def run(
    ctx: RunContext,
    athena,
    machines_table,
    incidents_table,
    insights_table,
    invoke_ia,
    branches=None,
    catalog_table=None,
) -> dict:
    stats = daily.from_rows(fetch_rows(athena, ctx.query_execution_id))
    machines = scan_all(machines_table, FilterExpression=Attr("machine_id").exists())
    # Solo ítems META (los EVT# no llevan incident_id/status en la raíz, contratos.md §9.1).
    incidents = scan_all(incidents_table, FilterExpression=Attr("incident_id").exists() & Attr("status").exists())
    catalog = fleet.load_catalog(catalog_table) if catalog_table is not None else fleet.Catalog()

    figures = {}
    for period, days in PERIODS.items():
        figures[f"kpis_{period}"] = kpis(stats, incidents, machines, ctx.today, days, catalog)
        write_insight(insights_table, f"kpis#{period}", figures[f"kpis_{period}"], ctx.run_at_iso, ctx.correlation_id)
        for zone, zone_kpis in kpis_by_zone(stats, incidents, machines, ctx.today, days, catalog).items():
            write_insight(insights_table, f"kpis#{period}", zone_kpis, ctx.run_at_iso, ctx.correlation_id, zone)
    figures["branches"] = [b for b in branches or [] if isinstance(b, dict)]

    text, prompt_version = executive_report(figures, invoke_ia, ctx.correlation_id)
    report = {
        "generated_at": ctx.run_at_iso,
        "summary_text": text,
        "prompt_version": prompt_version,
        "figures": figures,
    }
    write_insight(insights_table, "report#daily", report, ctx.run_at_iso, ctx.correlation_id)
    return {"kind": "kpis_report", "prompt_version": prompt_version}
