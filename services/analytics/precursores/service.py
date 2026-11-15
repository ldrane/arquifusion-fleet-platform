"""Firmas pre-falla (TAREA-12): patrones de anomalías que preceden a las fallas.

Para cada incidente cerrado/resuelto de los últimos 90 días se busca la primera anomalía de su máquina en la
ventana previa de 72 h (`first_signal`): su variable dominante (`top_factors[0]`) y cuánto antes apareció
(`lead_time_h`). Agrupando por modelo se calcula, por variable, qué proporción de fallas precedió (`share`), la
mediana de anticipación (`median_lead_time_h`) y la mediana del z-score (`median_z`).

Salida (insight `precursors`, GET /v1/analytics/precursors): `{"precursors": [{"model", "n_incidents",
"signatures": [{variable, share, median_lead_time_h, median_z}], "headline"}]}`, ordenada por `n_incidents`
descendente. Los modelos con menos de 3 incidentes se ignoran.
"""

import statistics
from collections import defaultdict
from datetime import datetime, timedelta

from analytics_common.dynamo import scan_all
from analytics_common.insights_store import write_insight
from analytics_common.run_context import RunContext
from boto3.dynamodb.conditions import Attr, Key

WINDOW_DAYS = 90
LEAD_WINDOW_H = 72
MIN_INCIDENTS = 3
MAX_SIGNATURES = 3
SIGNAL_STATUSES = ("closed", "resolved")


def _parse(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) if value else None
    except ValueError:
        return None


def _median(values: list[float]) -> float:
    return round(float(statistics.median(values)), 2) if values else 0.0


def _first_signal(incident: dict, anomalies: list[dict]) -> dict | None:
    """Anomalía más antigua dentro de las `LEAD_WINDOW_H` h previas al incidente."""
    detected = _parse(incident.get("detected_at"))
    if not detected:
        return None
    floor = detected - timedelta(hours=LEAD_WINDOW_H)
    candidates = []
    for anomaly in anomalies:
        when = _parse(anomaly.get("detected_at"))
        if when and floor <= when <= detected:
            candidates.append((when, anomaly))
    if not candidates:
        return None
    return min(candidates, key=lambda pair: pair[0])[1]


def _signals(incidents: list[dict], anomalies_by_machine: dict[str, list[dict]],
             model_by_machine: dict[str, str]) -> dict[str, list[dict | None]]:
    """`model` → lista (una por incidente) con la firma de su `first_signal` o `None` si no hubo señal previa."""
    grouped: dict[str, list[dict | None]] = defaultdict(list)
    for incident in incidents:
        machine = incident.get("machine_id")
        first = _first_signal(incident, anomalies_by_machine.get(machine, []))
        model = incident.get("model") or model_by_machine.get(machine) or (first or {}).get("model")
        if not model:
            continue
        if not first:
            grouped[model].append(None)
            continue
        factors = first.get("top_factors") or []
        if not factors:
            grouped[model].append(None)
            continue
        variable = factors[0].get("variable")
        z = factors[0].get("z_score")
        detected = _parse(incident.get("detected_at"))
        signal_at = _parse(first.get("detected_at"))
        grouped[model].append({
            "variable": variable,
            "lead_time_h": round((detected - signal_at).total_seconds() / 3600, 1) if detected and signal_at else 0.0,
            "z": float(z) if isinstance(z, (int, float)) else 0.0,
        })
    return grouped


def build_precursors(incidents: list[dict], anomalies_by_machine: dict[str, list[dict]],
                     model_by_machine: dict[str, str] | None = None) -> list[dict]:
    """Firmas por modelo, ordenadas por número de incidentes (TAREA-12)."""
    grouped = _signals(incidents, anomalies_by_machine, model_by_machine or {})
    out = []
    for model, signals in grouped.items():
        if len(signals) < MIN_INCIDENTS:
            continue
        by_variable: dict[str, list[dict]] = defaultdict(list)
        for signal in signals:
            if signal:
                by_variable[signal["variable"]].append(signal)
        signatures = [
            {
                "variable": variable,
                "share": round(len(items) / len(signals), 2),
                "median_lead_time_h": _median([i["lead_time_h"] for i in items]),
                "median_z": _median([i["z"] for i in items]),
            }
            for variable, items in by_variable.items()
        ]
        signatures.sort(key=lambda s: (-s["share"], s["variable"]))
        signatures = [s for s in signatures if s["variable"]][:MAX_SIGNATURES]
        if not signatures:
            continue
        best = signatures[0]
        out.append({
            "model": model,
            "n_incidents": len(signals),
            "signatures": signatures,
            "headline": (
                f"En {model}, {best['share'] * 100:.0f} % de las fallas fueron precedidas por "
                f"{best['variable']} ({best['median_z']:+.1f}σ) ~{best['median_lead_time_h']:.0f} h antes"
            ),
        })
    out.sort(key=lambda group: (-group["n_incidents"], group["model"]))
    return out


def _recent_incidents(incidents_table, since: datetime) -> list[dict]:
    items = scan_all(incidents_table, FilterExpression=Attr("sk").eq("META") & Attr("status").is_in(SIGNAL_STATUSES))
    return [
        i
        for i in items
        if i.get("machine_id") and (when := _parse(i.get("detected_at"))) and when >= since
    ]


def _anomalies(anomalies_table, machine_id: str, since_iso: str) -> list[dict]:
    page = anomalies_table.query(
        KeyConditionExpression=Key("pk").eq(machine_id) & Key("sk").gte(since_iso),
        ScanIndexForward=False,
    )
    return page.get("Items", [])


def run(ctx: RunContext, incidents_table, anomalies_table, machines_table, insights_table) -> dict:
    since = ctx.run_at - timedelta(days=WINDOW_DAYS)
    incidents = _recent_incidents(incidents_table, since)
    machines = scan_all(machines_table, FilterExpression=Attr("machine_id").exists())
    model_by_machine = {m["machine_id"]: m.get("model") for m in machines if m.get("model")}

    anomalies_by_machine = {
        incident["machine_id"]: _anomalies(
            anomalies_table,
            incident["machine_id"],
            (since - timedelta(hours=LEAD_WINDOW_H)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        for incident in incidents
    }
    precursors = build_precursors(incidents, anomalies_by_machine, model_by_machine)
    write_insight(insights_table, "precursors", {"precursors": precursors}, ctx.run_at_iso, ctx.correlation_id)
    return {
        "kind": "precursors",
        "models": len(precursors),
        "signatures": sum(len(p["signatures"]) for p in precursors),
        "incidents": len(incidents),
    }
