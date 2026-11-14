"""Formato de los ítems de la tabla `Insights` (contratos.md §9).

Los escribe la Persona A (AnalisisDiario, Reentrenamiento); los lee `api-lectura` (Persona C).
`data` es EXACTAMENTE el campo `data` de la respuesta del endpoint correspondiente en openapi.yaml.
"""

LATEST = "LATEST"

# kind -> endpoint que lo expone
KINDS: dict[str, str] = {
    "maintenance_plan": "GET /v1/maintenance/plan",
    "parts_ranking": "GET /v1/parts/ranking",
    "parts_forecast#7": "GET /v1/parts/forecast?horizon_days=7",
    "parts_forecast#30": "GET /v1/parts/forecast?horizon_days=30",
    "parts_forecast#90": "GET /v1/parts/forecast?horizon_days=90",
    "fuel#7d": "GET /v1/analytics/fuel?period=7d",
    "fuel#30d": "GET /v1/analytics/fuel?period=30d",
    "productivity#7d": "GET /v1/analytics/productivity?period=7d",
    "productivity#30d": "GET /v1/analytics/productivity?period=30d",
    "kpis#7d": "GET /v1/analytics/kpis?period=7d",
    "kpis#30d": "GET /v1/analytics/kpis?period=30d",
    "report#daily": "GET /v1/reports/latest?type=daily",
    "report#weekly": "GET /v1/reports/latest?type=weekly",
    "ml_model": "GET /v1/ml/model",
}


def items(kind: str, day: str, data, generated_at: str, correlation_id: str) -> list[dict]:
    """Devuelve los 2 ítems a escribir: el histórico del día (`sk=YYYY-MM-DD`) y `sk=LATEST`, que es el que lee C."""
    if kind not in KINDS:
        raise ValueError(f"kind desconocido: {kind}")
    base = {"pk": kind, "data": data, "generated_at": generated_at, "correlation_id": correlation_id}
    return [{**base, "sk": day}, {**base, "sk": LATEST}]
