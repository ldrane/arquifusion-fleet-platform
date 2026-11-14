"""api_lectura contra DynamoDB simulado (moto) cargado con los seeds reales (contracts/fixtures/seed)."""
import base64
import copy
import json
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

HERE = Path(__file__).resolve()
REPO = HERE.parents[4]
sys.path[:0] = [str(HERE.parents[1]), str(HERE.parents[2] / "common"), str(REPO / "services" / "shared"), str(REPO / "scripts")]

import service  # noqa: E402
import seed  # noqa: E402
import seed_data  # noqa: E402
from arquifusion_shared.errors import ApiError  # noqa: E402

BASE_EVENT = json.loads((REPO / "contracts" / "fixtures" / "api" / "get_me.event.json").read_text(encoding="utf-8"))

# tabla (sufijo) -> GSIs (dynamodb.md / contratos.md §9.1)
TABLES = {
    "machines": [("by_zone", "zone", "machine_id")],
    "machine-state": [],
    "anomalies": [("by_zone", "zone", "detected_at")],
    "incidents": [("by_machine", "machine_id", "detected_at"), ("by_status", "status", "detected_at")],
    "technicians": [("by_zone", "zone", "technician_id")],
    "inventory": [("by_component", "component_id", "warehouse_id")],
    "catalog": [],
    "warehouses": [],
    "maintenance-records": [],
    "insights": [],
}


def _create(ddb, name, gsis):
    attrs = {"pk", "sk"} | {g[1] for g in gsis} | {g[2] for g in gsis}
    params = {
        "TableName": f"arquifusion-t-{name}",
        "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        "AttributeDefinitions": [{"AttributeName": a, "AttributeType": "S"} for a in sorted(attrs)],
    }
    if gsis:
        params["GlobalSecondaryIndexes"] = [
            {"IndexName": i, "KeySchema": [{"AttributeName": h, "KeyType": "HASH"}, {"AttributeName": r, "KeyType": "RANGE"}],
             "Projection": {"ProjectionType": "ALL"}} for i, h, r in gsis
        ]
    ddb.create_table(**params)
    return boto3.resource("dynamodb", region_name="us-east-1").Table(params["TableName"])


def _put(table, item):
    table.put_item(Item=json.loads(json.dumps(item), parse_float=__import__("decimal").Decimal))


INCIDENT = {
    "pk": "INC#INC-01", "sk": "META", "incident_id": "INC-01", "machine_id": "EX-023", "machine_ids": ["EX-023"],
    "zone": "norte", "severity": "high", "status": "assigned", "detected_at": "2026-11-14T10:00:00Z",
    "assigned_technician_id": "TEC-07", "technician_score": 0.98, "ack_token": "SECRETO", "resolve_token": "SECRETO2",
    "execution_arn": "arn:x", "ai_diagnosis": {"probable_cause": "Rodamiento", "confidence": 0.8},
}


class FakeFirebase:
    def __init__(self, fail_fcm=False):
        self.minted, self.registered, self.fail_fcm = [], [], fail_fcm

    def mint(self, uid, claims):
        self.minted.append((uid, claims))
        return "custom-token"

    def register_fcm_token(self, uid, profile, token):
        if self.fail_fcm:
            raise RuntimeError("sin red")
        self.registered.append((uid, profile, token))


@pytest.fixture()
def deps():
    with mock_aws():
        ddb = boto3.client("dynamodb", region_name="us-east-1")
        tables = {name.replace("-", "_"): _create(ddb, name, gsis) for name, gsis in TABLES.items()}
        data = seed_data.build_all()
        for dataset in ("machines", "technicians", "inventory", "warehouses", "catalog", "machine_models"):
            target = tables[seed.KEY_SCHEMA[dataset]["table"].replace("-", "_")]
            for record in data[dataset]:
                target.put_item(Item=seed.to_item(dataset, record))
        _put(tables["incidents"], INCIDENT)
        _put(tables["incidents"], {**INCIDENT, "pk": "INC#INC-02", "incident_id": "INC-02", "severity": "critical",
                                   "status": "closed", "detected_at": "2026-11-13T08:00:00Z",
                                   "resolved_at": "2026-11-13T10:00:00Z", "downtime_minutes": 120})
        _put(tables["incidents"], {**INCIDENT, "pk": "INC#INC-03", "incident_id": "INC-03", "machine_id": "EX-001",
                                   "machine_ids": ["EX-001"], "zone": "sur", "severity": "critical",
                                   "detected_at": "2026-11-14T09:00:00Z"})
        # Ítem de historial: NO debe salir en listas (#26)
        _put(tables["incidents"], {"pk": "INC#INC-01", "sk": "EVT#2026-11-14T10:00:01Z#e1", "entity": "incident_event",
                                   "event_type": "incident.assigned"})
        _put(tables["machine_state"], {"pk": "EX-023", "sk": "AGG#1h#2026-11-14T10", "count": 2, "vars": {
            "temperature_c": {"min": 90, "max": 96.4, "sum": 186.4, "avg": 93.2},
            "vibration_mm_s": {"min": 7, "max": 7.9, "sum": 14.9, "avg": 7.45}}})
        _put(tables["machine_state"], {"pk": "EX-023", "sk": "LAST", "reading": {"machine_id": "EX-023", "temperature_c": 96.4}})
        _put(tables["anomalies"], {"pk": "EX-023", "sk": "2026-11-14T09:59:00Z#a1", "anomaly_id": "a1", "machine_id": "EX-023",
                                   "zone": "norte", "detected_at": "2026-11-14T09:59:00Z", "severity": "high",
                                   "top_factors": [{"variable": "vibration_mm_s", "z_score": 3.1, "direction": "high"}]})
        _put(tables["maintenance_records"], {"pk": "EX-023", "sk": "2026-11-13T10:00:00Z#MR-1", "record_id": "MR-1",
                                             "machine_id": "EX-023", "type": "corrective", "performed_at": "2026-11-13T10:00:00Z",
                                             "components": [{"component_id": "CMP-014", "quantity": 1}], "cost_usd": 450})
        _put(tables["insights"], {"pk": "kpis#7d", "sk": "LATEST", "generated_at": "2026-11-14T06:00:00Z",
                                  "data": {"availability_pct": 93.5, "mtbf_hours": 120, "open_incidents": 3}})
        _put(tables["insights"], {"pk": "kpis#7d", "sk": "LATEST#norte", "generated_at": "2026-11-14T06:00:00Z",
                                  "data": {"availability_pct": 91.0, "mtbf_hours": 100, "open_incidents": 1}})
        _put(tables["insights"], {"pk": "fuel#7d", "sk": "LATEST", "data": [
            {"machine_id": "EX-023", "zone": "norte", "lph": 41.2}, {"machine_id": "EX-001", "zone": "sur", "lph": 40}]})
        _put(tables["insights"], {"pk": "parts_forecast#30", "sk": "LATEST", "data": [
            {"warehouse_id": "WH-01", "component_id": "CMP-014"}, {"warehouse_id": "WH-02", "component_id": "CMP-021"}]})
        yield service.Deps(tables=tables, firebase=FakeFirebase(), env={"DEFAULT_OPERATION_ID": "OP-01"})


def ev(method, resource, *, groups="tecnico", zone="norte", tech="TEC-07", path=None, qs=None, body=None):
    e = copy.deepcopy(BASE_EVENT)
    e.update(httpMethod=method, resource=resource, path=resource, pathParameters=path, queryStringParameters=qs,
             body=json.dumps(body) if body is not None else None)
    claims = e["requestContext"]["authorizer"]["claims"]
    claims["cognito:groups"] = groups
    claims["custom:zone"] = zone
    if tech:
        claims["custom:technician_id"] = tech
    else:
        claims.pop("custom:technician_id", None)
    return e


def err(deps, e):
    with pytest.raises(ApiError) as exc:
        service.run(e, deps)
    return exc.value.status, exc.value.code


# --------------------------------------------------------------------------- sesión
def test_me_incluye_technician_id(deps):
    data, _ = service.run(ev("GET", "/me"), deps)
    assert data == {"user_id": "u-tec-07", "email": "tec07@demo.arquifusion.local", "role": "tecnico",
                    "zone": "norte", "technician_id": "TEC-07"}


def test_me_no_tecnico_sin_technician_id(deps):
    data, _ = service.run(ev("GET", "/me", groups="supervisor", tech="TEC-07"), deps)
    assert data["technician_id"] is None


def test_firebase_token_claims_y_fcm(deps):
    data, meta = service.run(ev("POST", "/auth/firebase-token", body={"fcm_token": "tok-1"}), deps)
    assert data == {"firebase_token": "custom-token", "expires_in": 3600}
    assert deps.firebase.minted == [("u-tec-07", {"role": "tecnico", "zone": "norte", "technician_id": "TEC-07"})]
    uid, profile, token = deps.firebase.registered[0]
    assert (uid, token, profile["role"], profile["technician_id"]) == ("u-tec-07", "tok-1", "tecnico", "TEC-07")
    assert meta["fcm_registered"] is True


def test_firebase_token_global_sin_body(deps):
    data, meta = service.run(ev("POST", "/auth/firebase-token", groups="gerencia", zone="*", tech=None), deps)
    assert deps.firebase.minted[-1][1] == {"role": "gerencia", "zone": None, "technician_id": None}
    assert deps.firebase.registered == [] and meta == {}


def test_firebase_token_fcm_falla_no_rompe_login(deps):
    deps._firebase = FakeFirebase(fail_fcm=True)
    data, meta = service.run(ev("POST", "/auth/firebase-token", body={"fcm_token": "x"}), deps)
    assert data["firebase_token"] == "custom-token" and meta["fcm_registered"] is False


def test_firebase_token_body_invalido(deps):
    assert err(deps, ev("POST", "/auth/firebase-token", body={"fcm_token": 3})) == (400, "VALIDATION_ERROR")


# --------------------------------------------------------------------------- flota
def test_machines_zona_del_usuario_y_paginacion(deps):
    data, meta = service.run(ev("GET", "/machines", qs={"limit": "10"}), deps)
    assert len(data) == 10 and meta["next_cursor"]
    assert {m["location"]["zone"] for m in data} == {"norte"}
    assert set(data[0]) == {"machine_id", "model", "type", "location", "status", "severity", "health_score",
                            "last_seen_at", "open_incident_id"}
    seen = [m["machine_id"] for m in data]
    cursor = meta["next_cursor"]
    while cursor:
        page, meta = service.run(ev("GET", "/machines", qs={"limit": "10", "cursor": cursor}), deps)
        seen += [m["machine_id"] for m in page]
        cursor = meta["next_cursor"]
    norte = [m for m in seed_data.build_all()["machines"] if m["zone"] == "norte"]
    assert sorted(seen) == sorted(m["machine_id"] for m in norte) and len(set(seen)) == len(seen)


def test_machines_global_filtros(deps):
    data, _ = service.run(ev("GET", "/machines", groups="admin", zone="*", qs={"type": "excavator", "limit": "100"}), deps)
    assert data and {m["type"] for m in data} == {"excavator"}
    assert len({m["location"]["zone"] for m in data}) > 1


def test_machines_otra_zona_403_y_enum_400(deps):
    assert err(deps, ev("GET", "/machines", qs={"zone": "sur"})) == (403, "FORBIDDEN")
    assert err(deps, ev("GET", "/machines", qs={"status": "rota"})) == (400, "VALIDATION_ERROR")
    assert err(deps, ev("GET", "/machines", qs={"limit": "500"})) == (400, "VALIDATION_ERROR")


def test_machine_detail_numeros_y_latest_reading(deps):
    data, _ = service.run(ev("GET", "/machines/{machine_id}", path={"machine_id": "EX-023"}), deps)
    assert data["model"] == "CAT-336" and isinstance(data["health_score"], int)
    assert isinstance(data["operating_hours"], float)
    assert data["latest_reading"] == {"machine_id": "EX-023", "temperature_c": 96.4}
    assert data["open_incident_id"] is None and data["top_factors"] == []


def test_machine_de_otra_zona_404(deps):
    sur = next(m for m in seed_data.build_all()["machines"] if m["zone"] == "sur")["machine_id"]
    assert err(deps, ev("GET", "/machines/{machine_id}", path={"machine_id": sur})) == (404, "NOT_FOUND")


def test_telemetry(deps):
    qs = {"from": "2026-11-14T08:00:00Z", "to": "2026-11-14T12:00:00Z", "resolution": "1m"}
    data, meta = service.run(ev("GET", "/machines/{machine_id}/telemetry", path={"machine_id": "EX-023"}, qs=qs), deps)
    assert meta["resolution"] == "1h"
    assert data == [{"bucket_start": "2026-11-14T10:00:00Z", "temperature_c": {"min": 90, "avg": 93.2, "max": 96.4},
                     "vibration_mm_s": {"min": 7, "avg": 7.45, "max": 7.9},
                     "pressure_bar": {"min": None, "avg": None, "max": None},
                     "fuel_rate_lph": {"min": None, "avg": None, "max": None}, "health_score": None}]
    bad = {"from": "2026-11-14T12:00:00Z", "to": "2026-11-14T08:00:00Z"}
    assert err(deps, ev("GET", "/machines/{machine_id}/telemetry", path={"machine_id": "EX-023"}, qs=bad)) == (400, "VALIDATION_ERROR")
    assert err(deps, ev("GET", "/machines/{machine_id}/telemetry", groups="operador", path={"machine_id": "EX-023"}, qs=qs)) == (403, "FORBIDDEN")


def test_timeline(deps, monkeypatch):
    from datetime import UTC, datetime

    e = ev("GET", "/machines/{machine_id}/timeline", path={"machine_id": "EX-023"})
    data, _ = service.get_timeline(e, deps, service.current_user(e), now=datetime(2026, 11, 14, 12, tzinfo=UTC))
    kinds = [x["kind"] for x in data["events"]]
    assert kinds == ["incident", "anomaly", "corrective", "incident"]
    assert data["events"][0]["ref_id"] == "INC-01"
    assert data["kpis"] == {"mtbf_hours": 2160.0, "mttr_hours": 2.0, "availability_pct": 99.9}


# --------------------------------------------------------------------------- incidentes
def test_incidents_orden_zona_y_sin_secretos(deps):
    data, meta = service.run(ev("GET", "/incidents"), deps)
    assert [i["incident_id"] for i in data] == ["INC-01", "INC-02"]  # abierto primero; INC-03 es de sur
    assert meta == {"count": 2, "next_cursor": None}
    body = json.dumps(data)
    assert "SECRETO" not in body and "execution_arn" not in body and "EVT#" not in body
    assert data[0]["machine_ids"] == ["EX-023"] and data[0]["machine_id"] == "EX-023"
    assert data[0]["technician_score"] == 0.98 and data[0]["child_incident_ids"] == []


def test_incidents_por_maquina_y_estado(deps):
    data, _ = service.run(ev("GET", "/incidents", groups="admin", zone="*", qs={"machine_id": "EX-023"}), deps)
    assert {i["incident_id"] for i in data} == {"INC-01", "INC-02"}
    data, _ = service.run(ev("GET", "/incidents", groups="admin", zone="*", qs={"status": "assigned"}), deps)
    assert [i["incident_id"] for i in data] == ["INC-03", "INC-01"]  # critical antes que high


def test_incident_detalle_y_otra_zona(deps):
    data, _ = service.run(ev("GET", "/incidents/{incident_id}", path={"incident_id": "INC-01"}), deps)
    assert data["status"] == "assigned" and "ack_token" not in data
    assert err(deps, ev("GET", "/incidents/{incident_id}", path={"incident_id": "INC-03"})) == (404, "NOT_FOUND")


# --------------------------------------------------------------------------- técnicos, inventario, insights
def test_technicians_eta_y_rbac(deps):
    assert err(deps, ev("GET", "/technicians")) == (403, "FORBIDDEN")
    data, _ = service.run(ev("GET", "/technicians", groups="supervisor", qs={"machine_id": "EX-023", "specialty": "motor"}), deps)
    assert data and all(t["location"]["zone"] == "norte" and "motor" in t["specialties"] for t in data)
    assert data[0]["technician_id"] == "TEC-07" and isinstance(data[0]["eta_minutes"], int)


def test_inventory_alertas(deps):
    data, _ = service.run(ev("GET", "/inventory", groups="mantenimiento", zone="*", qs={"alert": "low_stock"}), deps)
    assert data and {i["alert"] for i in data} == {"low_stock"}
    data, _ = service.run(ev("GET", "/inventory", groups="mantenimiento", zone="*", qs={"warehouse_id": "WH-04"}), deps)
    assert data and {i["warehouse_id"] for i in data} == {"WH-04"}


def test_insights(deps):
    data, meta = service.run(ev("GET", "/analytics/kpis", groups="supervisor"), deps)
    assert data["availability_pct"] == 91.0 and meta["zone"] == "norte"
    data, _ = service.run(ev("GET", "/analytics/kpis", groups="gerencia", zone="*"), deps)
    assert data["open_incidents"] == 3
    data, _ = service.run(ev("GET", "/analytics/fuel", groups="supervisor"), deps)
    assert [r["machine_id"] for r in data] == ["EX-023"]
    data, _ = service.run(ev("GET", "/parts/forecast", groups="mantenimiento", zone="norte"), deps)
    assert [r["warehouse_id"] for r in data] == ["WH-01"]
    data, _ = service.run(ev("GET", "/parts/ranking", groups="admin", zone="*"), deps)
    assert data == []  # AnalisisDiario aún no corrió
    assert err(deps, ev("GET", "/reports/latest", groups="gerencia", zone="*")) == (404, "NOT_FOUND")
    assert err(deps, ev("GET", "/ml/model", groups="supervisor")) == (403, "FORBIDDEN")


def test_todas_las_rutas_get_de_api_lectura_estan_en_routes():
    import re

    spec = (REPO / "contracts" / "openapi.yaml").read_text(encoding="utf-8")
    ops = set()
    current = None
    for line in spec.splitlines():
        if m := re.match(r"^  (/[^:]*):\s*$", line):
            current = m.group(1)
        elif m := re.match(r"^    (get|post|put):", line):
            method = m.group(1).upper()
        elif "x-lambda: api-lectura" in line:
            ops.add((method, current))
    assert ops == set(service.ROUTES)
    assert not any(p.startswith("/v1") for _, p in ops)


def test_cursor_invalido(deps):
    bad = base64.urlsafe_b64encode(b"-5").decode()
    assert err(deps, ev("GET", "/incidents", qs={"cursor": bad})) == (400, "VALIDATION_ERROR")
