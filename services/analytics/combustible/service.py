"""Análisis de combustible (RF-07.1, RF-07.2, RF-07.3, RF-07.4).

Normaliza el consumo (L/h en operación y L/t movida), lo compara con máquinas del mismo tipo y con el propio
historial (días 31-90), detecta aumentos progresivos (pendiente de los últimos 30 días) y sugiere causas probables
con reglas sobre carga, RPM, temperatura y ralentí.
Salida: `insights` `fuel#7d` y `fuel#30d` (forma de GET /v1/analytics/fuel).

Pares = máquinas del mismo MODELO (un KOM-PC2000 consume ~3× un CAT-336, #13). Si el modelo tiene menos de
MIN_PEERS máquinas, la referencia es el `nominal` de `fuel_rate_lph` del catálogo `MODEL#…`, y si tampoco existe,
la mediana del tipo. L/t usa la capacidad derivada de `payload_t` del catálogo.
"""

from datetime import date

from analytics_common import daily, fleet
from analytics_common.athena import fetch_rows
from analytics_common.insights_store import write_insight
from analytics_common.run_context import RunContext

PERIODS = {"7d": 7, "30d": 30}
HISTORY_DAYS = 90
TREND_DAYS = 30
PROGRESSIVE_PCT_PER_WEEK = 2.0
FLAG_VS_PEERS_PCT = 15.0
FLAG_VS_HISTORY_PCT = 10.0
HIGH_LOAD_PCT = 85.0
HIGH_RPM_VS_PEERS = 1.10
HIGH_TEMPERATURE_C = 95.0
HIGH_IDLE_SHARE = 0.35
MIN_PEERS = 3


def _pct(value: float | None, reference: float | None) -> float:
    if not value or not reference:
        return 0.0
    return round((value / reference - 1) * 100, 1)


def progressive_increase(stats: list[daily.DailyStat], today: date) -> bool:
    """Pendiente diaria del consumo en 30 días, expresada en % del promedio por semana."""
    recent = [s for s in daily.window(stats, today, TREND_DAYS) if s.fuel_lph is not None]
    points = [(float((s.day - today).days), s.fuel_lph) for s in recent]
    mean = sum(y for _, y in points) / len(points) if points else 0.0
    if mean == 0:
        return False
    return daily.linear_slope(points) * 7 / mean * 100 >= PROGRESSIVE_PCT_PER_WEEK


def probable_causes(current: list[daily.DailyStat], peer_rpm: float | None, progressive: bool) -> list[str]:
    causes = []
    load = daily.weighted_avg(current, "avg_load_pct") or 0.0
    rpm = daily.weighted_avg(current, "avg_rpm")
    temp = daily.weighted_avg(current, "avg_temperature_c", weight="readings") or 0.0
    readings = sum(s.readings for s in current) or 1
    idle_share = sum(s.idle_readings for s in current) / readings
    if load >= HIGH_LOAD_PCT:
        causes.append("Sobrecarga operativa sostenida")
    if rpm and peer_rpm and rpm >= peer_rpm * HIGH_RPM_VS_PEERS:
        causes.append("Operación a RPM elevadas (estilo de manejo)")
    if temp >= HIGH_TEMPERATURE_C:
        causes.append("Motor trabajando caliente (refrigeración o lubricación)")
    if idle_share >= HIGH_IDLE_SHARE:
        causes.append("Ralentí prolongado")
    if progressive:
        causes.append("Desgaste progresivo (inyectores, filtros o componentes del motor)")
    if not causes:
        causes.append("Revisar inyectores y filtro de aire")
    return causes


def _peer_reference(
    mid: str,
    model: dict[str, str | None],
    machine_type: dict[str, str],
    values: dict[str, float | None],
    catalog: fleet.Catalog,
    variable: str,
) -> float | None:
    """Mediana de las máquinas del mismo modelo; si son pocas, el nominal del catálogo; si no, el tipo."""
    same_model = [values[m] for m in values if model[m] == model[mid] and model[mid] and values[m] is not None]
    if len(same_model) >= MIN_PEERS:
        return daily.median(same_model)
    nominal = catalog.nominal_mean(model[mid], variable)
    if nominal is not None:
        return nominal
    return daily.median([values[m] for m in values if machine_type[m] == machine_type[mid] and values[m] is not None])


def analyze(
    stats: list[daily.DailyStat], today: date, period_days: int, catalog: fleet.Catalog | None = None
) -> list[dict]:
    """Una fila por máquina con datos en el periodo, ordenada de mayor a menor desvío frente a sus pares."""
    catalog = catalog or fleet.Catalog()
    grouped = daily.by_machine(stats)
    current = {mid: daily.window(s, today, period_days) for mid, s in grouped.items()}
    current = {mid: s for mid, s in current.items() if s}
    lph = {mid: daily.weighted_avg(s, "fuel_lph") for mid, s in current.items()}
    rpm = {mid: daily.weighted_avg(s, "avg_rpm") for mid, s in current.items()}
    machine_type = {mid: s[0].machine_type for mid, s in current.items()}
    model = {mid: s[-1].model for mid, s in current.items()}

    rows = []
    for mid, period_stats in current.items():
        value = lph[mid] or 0.0
        load = daily.weighted_avg(period_stats, "avg_load_pct") or 0.0
        tons_per_hour = load / 100 * catalog.capacity_tph(model[mid], machine_type[mid])
        history = daily.window(grouped[mid], today, HISTORY_DAYS - period_days, offset=period_days)
        peer_lph = _peer_reference(mid, model, machine_type, lph, catalog, "fuel_rate_lph")
        peer_rpm = _peer_reference(mid, model, machine_type, rpm, catalog, "rpm")
        vs_peers = _pct(value, peer_lph)
        vs_history = _pct(value, daily.weighted_avg(history, "fuel_lph"))
        progressive = progressive_increase(grouped[mid], today)
        flagged = vs_peers >= FLAG_VS_PEERS_PCT or vs_history >= FLAG_VS_HISTORY_PCT or progressive
        rows.append(
            {
                "machine_id": mid,
                "zone": period_stats[-1].zone,
                "lph": round(value, 2),
                "l_per_ton": round(value / tons_per_hour, 3) if tons_per_hour else 0.0,
                "vs_peers_pct": vs_peers,
                "vs_own_history_pct": vs_history,
                "progressive_increase": progressive,
                "probable_causes": (
                    probable_causes(period_stats, peer_rpm, progressive) if flagged else []
                ),
            }
        )
    rows.sort(key=lambda r: r["vs_peers_pct"], reverse=True)
    return rows


def run(ctx: RunContext, athena, insights_table, catalog_table=None) -> dict:
    stats = daily.from_rows(fetch_rows(athena, ctx.query_execution_id))
    catalog = fleet.load_catalog(catalog_table) if catalog_table is not None else fleet.Catalog()
    flagged = 0
    for period, days in PERIODS.items():
        rows = analyze(stats, ctx.today, days, catalog)
        write_insight(insights_table, f"fuel#{period}", rows, ctx.run_at_iso, ctx.correlation_id)
        if period == "7d":
            flagged = sum(1 for r in rows if r["probable_causes"])
    return {"kind": "fuel", "flagged_7d": flagged}
