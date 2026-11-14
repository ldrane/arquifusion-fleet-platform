"""scoring-tecnicos (RF-06.2, RF-06.3, TRZ-03). Contrato: contratos.md §8.3, fixtures `internal/scoring_*.json`.

Misma fórmula que `frontend/src/lib/scoring.ts` (un único shape `Candidate`):
- candidatos = técnicos de la zona del incidente (GSI `by_zone`) que no están en `exclude_technician_ids`;
- breakdown en [0, 1]: specialty (1/0, 0.5 si no hay required_specialty), eta = max(0, 1 − eta_min/45),
  availability (1/0), load = max(0, 1 − current_load/3);
- eta_min = haversine a 25 km/h + 2 min (mínimo 1);
- score = Σ peso(severidad) × breakdown, redondeado a 2 decimales; orden: score desc, eta_min asc.
`selected` = primer candidato disponible; `null` si no hay ninguno (la SFN escala).
"""
import math
from decimal import Decimal

WEIGHTS = {
    "critical": {"specialty": 0.30, "eta": 0.45, "availability": 0.15, "load": 0.10},
    "high": {"specialty": 0.35, "eta": 0.35, "availability": 0.15, "load": 0.15},
    "medium": {"specialty": 0.40, "eta": 0.25, "availability": 0.15, "load": 0.20},
    "low": {"specialty": 0.40, "eta": 0.20, "availability": 0.15, "load": 0.25},
    "info": {"specialty": 0.40, "eta": 0.20, "availability": 0.15, "load": 0.25},
}
SPEED_KMH = 25
PREP_MIN = 2
ETA_CAP_MIN = 45
MAX_LOAD = 3


def _num(value, default=0.0) -> float:
    if value is None:
        return default
    return float(value) if isinstance(value, (int, float, Decimal, str)) else default


def haversine_km(a: dict, b: dict) -> float:
    r = 6371
    lat1, lon1, lat2, lon2 = map(math.radians, (_num(a["lat"]), _num(a["lon"]), _num(b["lat"]), _num(b["lon"])))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def eta_minutes(a: dict, b: dict) -> int:
    # Math.round de JS: redondea .5 hacia arriba
    return max(1, math.floor(haversine_km(a, b) / SPEED_KMH * 60 + PREP_MIN + 0.5))


def _r2(x: float) -> float:
    return math.floor(x * 100 + 0.5) / 100


def score_technicians(techs: list[dict], location: dict, severity: str, specialty: str | None, exclude=()) -> list:
    w = WEIGHTS.get(severity, WEIGHTS["medium"])
    out = []
    for t in techs:
        if t.get("technician_id") in exclude or not t.get("location"):
            continue
        # Sin ubicación de la máquina (contexto falló): ETA neutro = tope, decide especialidad/carga
        eta = eta_minutes(t["location"], location) if location and location.get("lat") is not None else ETA_CAP_MIN
        b = {
            "specialty": 0.5 if not specialty else (1 if specialty in (t.get("specialties") or []) else 0),
            "eta": _r2(max(0.0, 1 - eta / ETA_CAP_MIN)),
            "availability": 1 if t.get("available") else 0,
            "load": _r2(max(0.0, 1 - _num(t.get("current_load")) / MAX_LOAD)),
        }
        raw = sum(w[k] * (max(0.0, 1 - eta / ETA_CAP_MIN) if k == "eta" else b[k]) for k in w)
        out.append(
            {
                "technician_id": t["technician_id"],
                "name": t.get("name"),
                "score": _r2(raw),
                "eta_min": eta,
                "breakdown": b,
            }
        )
    out.sort(key=lambda c: (-c["score"], c["eta_min"]))
    return out


def rank(request: dict, techs: list[dict]) -> dict:
    severity = request.get("severity") or "medium"
    candidates = score_technicians(
        techs,
        request.get("location"),
        severity,
        request.get("required_specialty"),
        set(request.get("exclude_technician_ids") or []),
    )
    available = {t["technician_id"] for t in techs if t.get("available")}
    selected = next((c["technician_id"] for c in candidates if c["technician_id"] in available), None)
    return {"selected": selected, "weights": WEIGHTS.get(severity, WEIGHTS["medium"]), "candidates": candidates}


def _default_deps() -> dict:
    import boto3
    from arquifusion_shared import config

    return {"technicians": boto3.resource("dynamodb").Table(config.table("technicians"))}


def load_technicians(table, zone: str) -> list[dict]:
    from boto3.dynamodb.conditions import Key

    items, kwargs = [], {"IndexName": "by_zone", "KeyConditionExpression": Key("zone").eq(zone)}
    while True:
        page = table.query(**kwargs)
        items += page.get("Items", [])
        if "LastEvaluatedKey" not in page:
            return items
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def run(event: dict, deps: dict | None = None) -> dict:
    deps = deps or _default_deps()
    loader = deps.get("load") or (lambda zone: load_technicians(deps["technicians"], zone))
    return rank(event, loader(event["zone"]))


