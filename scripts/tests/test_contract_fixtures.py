"""Las fixtures de contrato (contracts/fixtures) son coherentes con los seeds (auditoría #12, #19, #21).

Correr: python -m pytest scripts/tests -q
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import seed  # noqa: E402
import seed_data  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "contracts" / "fixtures"
DATA = seed_data.build_all()
MACHINES = {m["machine_id"]: m for m in DATA["machines"]}
TECHS = {t["technician_id"]: t for t in DATA["technicians"]}
CATALOG = {c["component_id"]: c for c in DATA["catalog"]}
MODELS = {m["model_id"]: m for m in DATA["machine_models"]}
SPECIALTIES = {"motor", "hidraulica", "electrica", "neumaticos"}
BUS = "arquifusion-dev-fleet-events"


def _load(rel: str):
    return json.loads((FIX / rel).read_text(encoding="utf-8"))


def _detail(rel: str) -> dict:
    entries = _load(rel)
    assert len(entries) == 1
    assert entries[0]["EventBusName"] == BUS, "contratos.md §3: bus arquifusion-{stage}-fleet-events"
    return json.loads(entries[0]["Detail"])


# --------------------------------------------------------------------------- seeds exportados
def test_fixtures_seed_coinciden_byte_a_byte_con_build_all():
    for name, records in DATA.items():
        expected = json.dumps(records, ensure_ascii=False, indent=2) + "\n"
        actual = (FIX / "seed" / f"{name}.json").read_text(encoding="utf-8")
        assert actual == expected, f"{name}.json desactualizado: python scripts/seed.py export"
    manifest = _load("seed/_manifest.json")
    assert manifest["seed_version"] == seed_data.SEED_VERSION
    assert manifest["counts"] == {k: len(v) for k, v in DATA.items()}


# --------------------------------------------------------------------------- telemetría
def test_telemetry_batch_es_ex023_del_seed():
    reading = _load("api/telemetry_batch.json")["readings"][0]
    ex = MACHINES[reading["machine_id"]]
    assert reading["machine_id"] == "EX-023"
    assert (reading["model"], reading["type"]) == (ex["model"], ex["type"]) == ("CAT-336", "excavator")
    assert reading["location"] == ex["location"]
    assert reading["operating_hours"] >= ex["operating_hours"]
    assert set(MODELS[ex["model"]]["nominal"]) <= set(reading)


# --------------------------------------------------------------------------- ia-gemini
def test_diagnose_request_coherente_con_seed():
    req = _load("ia/diagnose_request.json")
    p = req["payload"]
    ex = MACHINES[p["machine_id"]]
    assert (p["model"], p["machine_type"], p["zone"]) == (ex["model"], ex["type"], ex["zone"])
    parts = p["candidate_parts"]
    # candidate_parts = MODEL#<model>.component_ids + catalog (contratos.md §8.1)
    assert [c["component_id"] for c in parts] == MODELS[ex["model"]]["component_ids"]
    for c in parts:
        assert c["name"] == CATALOG[c["component_id"]]["name"]
        assert c["specialty"] == CATALOG[c["component_id"]]["specialty"] in SPECIALTIES
    assert "CMP-014" in {c["component_id"] for c in parts}


def test_diagnose_response_solo_sugiere_candidatos_y_trae_prompt_version():
    req, resp = _load("ia/diagnose_request.json"), _load("ia/diagnose_response.json")
    allowed = {c["component_id"] for c in req["payload"]["candidate_parts"]}
    assert set(resp["result"]["parts_suggested"]) <= allowed
    assert resp["prompt_version"] == "diagnose-v1"
    assert set(resp) == {"result", "model", "degraded", "prompt_version", "latency_ms"}


# --------------------------------------------------------------------------- scoring
def _eta(a: dict, b: dict) -> int:  # misma fórmula que frontend/src/lib/geo.ts
    r = math.radians
    h = math.sin(r(b["lat"] - a["lat"]) / 2) ** 2 + math.cos(r(a["lat"])) * math.cos(r(b["lat"])) * math.sin(
        r(b["lon"] - a["lon"]) / 2
    ) ** 2
    return max(1, round(2 * 6371 * math.asin(math.sqrt(h)) / 25 * 60 + 2))


def test_scoring_request_coherente_con_seed_y_regla_de_especialidad():
    req = _load("internal/scoring_request.json")
    ex = MACHINES[req["machine_id"]]
    assert req["zone"] == ex["zone"] and req["location"] == ex["location"]
    assert req["required_specialty"] in SPECIALTIES
    # contratos.md §8.2: specialty del primer repuesto sugerido por diagnose
    first = _load("ia/diagnose_response.json")["result"]["parts_suggested"][0]
    assert req["required_specialty"] == CATALOG[first]["specialty"] == "motor"


def test_scoring_response_usa_tecnicos_reales_de_la_zona():
    req, resp = _load("internal/scoring_request.json"), _load("internal/scoring_response.json")
    cands = resp["candidates"]
    assert resp["selected"] == cands[0]["technician_id"] == "TEC-07"
    zone_techs = {t for t, v in TECHS.items() if v["zone"] == req["zone"]}
    assert {c["technician_id"] for c in cands} == zone_techs
    w = resp["weights"]
    for c in cands:
        assert set(c) == {"technician_id", "name", "score", "eta_min", "breakdown"}  # shape único (§8.3)
        tech = TECHS[c["technician_id"]]
        assert c["name"] == tech["name"]
        assert c["eta_min"] == _eta(tech["location"], req["location"])
        assert c["breakdown"]["specialty"] == (1 if req["required_specialty"] in tech["specialties"] else 0)
        assert c["breakdown"]["eta"] == round(max(0, 1 - c["eta_min"] / 45), 2)
        assert c["score"] == round(sum(w[k] * c["breakdown"][k] for k in w), 2)
    scores = [c["score"] for c in cands]
    assert scores == sorted(scores, reverse=True)


# --------------------------------------------------------------------------- eventos
def test_anomaly_detected_coherente_con_seed():
    data = _detail("events/anomaly_detected.json")["data"]
    assert MACHINES[data["machine_id"]]["zone"] == data["zone"]
    assert data["reading_ts"] == _load("api/telemetry_batch.json")["readings"][0]["timestamp"]


def test_machine_silent_usa_el_intervalo_del_seed():
    data = _detail("events/machine_silent.json")["data"]
    m = MACHINES[data["machine_id"]]
    assert data["expected_interval_s"] == m["expected_interval_s"] == seed_data.EXPECTED_INTERVAL_S == 60
    assert data["silence_threshold_s"] == 3 * data["expected_interval_s"]
    assert data["zone"] == m["zone"]


def test_incident_state_changed_usa_event_type_con_reglas():
    data = _detail("events/incident_state_changed.json")["data"]
    assert data["event_type"] in seed_data.NOTIFICATION_EVENT_TYPES
    assert data["technician_id"] in TECHS
    assert MACHINES[data["machine_id"]]["zone"] == data["zone"]


# --------------------------------------------------------------------------- identidad y pub/sub
def test_eventos_api_gw_traen_claims_del_tecnico():
    for rel in ("api/get_me.event.json", "api/technician_status.event.json"):
        claims = _load(rel)["requestContext"]["authorizer"]["claims"]
        tech = TECHS[claims["custom:technician_id"]]
        assert claims["cognito:username"] == tech["user_id"]
        assert claims["custom:zone"] == tech["zone"]
        assert claims["cognito:groups"] == "tecnico"


def test_notificacion_pubsub_apunta_a_un_usuario_real():
    msg = _load("pubsub/notificacion.json")
    assert msg["event_type"] in seed_data.NOTIFICATION_EVENT_TYPES
    assert msg["target"]["user_id"] in {t["user_id"] for t in TECHS.values()}


# --------------------------------------------------------------------------- seeds (#14, #19, #21)
def test_reglas_cubren_la_tabla_de_transiciones():
    expected = {
        "incident.detected", "incident.assigned", "incident.in_progress", "incident.escalated",
        "incident.resolved", "incident.closed", "machine.silent", "parts.shortage", "report.daily",
    }
    assert set(seed_data.NOTIFICATION_EVENT_TYPES) == expected
    assigned = [r for r in DATA["notification_rules"] if r["event_type"] == "incident.assigned"]
    assert any(r["role"] == "tecnico" and "push" in r["channels"] for r in assigned)


def test_cada_zona_tiene_almacen_y_los_tecnicos_usan_el_de_su_zona():
    wh = {w["warehouse_id"]: w for w in DATA["warehouses"]}
    for w in wh.values():
        cfg = seed_data.ZONES[w["zone"]]
        dist = math.dist((w["location"]["lat"], w["location"]["lon"]), cfg["center"])
        assert dist <= cfg["radius_deg"] and w["location"]["zone"] == w["zone"]
    for t in TECHS.values():
        assert wh[t["home_warehouse_id"]]["zone"] == t["zone"]
        assert t["location"]["zone"] == t["zone"]
        cfg = seed_data.ZONES[t["zone"]]
        assert math.dist((t["location"]["lat"], t["location"]["lon"]), cfg["center"]) <= cfg["radius_deg"]
    assert any(i["warehouse_id"] == "WH-04" for i in DATA["inventory"])
    assert "warehouses" in seed.KEY_SCHEMA  # se carga a DynamoDB ({p}-warehouses)


def test_modelos_exponen_lo_que_lee_la_analitica():
    for m in DATA["machine_models"]:
        assert {"maintenance_interval_h", "payload_t", "nominal", "component_ids"} <= set(m)
