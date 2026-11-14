import json
from decimal import Decimal
from pathlib import Path

import boto3
import pytest
import service
from moto import mock_aws

FIX = Path(__file__).parents[4] / "contracts" / "fixtures"
P = "arquifusion-test"


def load(rel):
    return json.loads((FIX / rel).read_text(), parse_float=Decimal)


def _table(ddb, name, gsis=(), sk=True):
    attrs = {"pk", "sk"} if sk else {"pk"}
    for _, h, r in gsis:
        attrs |= {h, r}
    kwargs = {
        "TableName": f"{P}-{name}",
        "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}]
        + ([{"AttributeName": "sk", "KeyType": "RANGE"}] if sk else []),
        "AttributeDefinitions": [{"AttributeName": a, "AttributeType": "S"} for a in sorted(attrs)],
    }
    if gsis:
        kwargs["GlobalSecondaryIndexes"] = [
            {
                "IndexName": n,
                "KeySchema": [{"AttributeName": h, "KeyType": "HASH"}, {"AttributeName": r, "KeyType": "RANGE"}],
                "Projection": {"ProjectionType": "ALL"},
            }
            for n, h, r in gsis
        ]
    ddb.create_table(**kwargs)
    return ddb.Table(f"{P}-{name}")


@pytest.fixture
def tables(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("DEFAULT_OPERATION_ID", "OP-01")
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        t = {
            "incidents": _table(ddb, "incidents", [("by_machine", "machine_id", "detected_at")]),
            "machines": _table(ddb, "machines"),
            "machine_state": _table(ddb, "machine-state"),
            "catalog": _table(ddb, "catalog"),
            "inventory": _table(ddb, "inventory", [("by_component", "component_id", "warehouse_id")]),
            "technicians": _table(ddb, "technicians"),
            "maintenance_records": _table(ddb, "maintenance-records"),
            "resource": ddb,
        }
        m = next(x for x in load("seed/machines.json") if x["machine_id"] == "EX-023")
        t["machines"].put_item(
            Item={
                k: v
                for k, v in {**m, "pk": "OP-01#EX-023", "sk": "META", "open_incident_id": "INC-01JC8ZK"}.items()
                if v is not None
            }
        )
        for c in load("seed/catalog.json"):
            t["catalog"].put_item(Item={**c, "pk": f"COMPONENT#{c['component_id']}", "sk": "META"})
        for mm in load("seed/machine_models.json"):
            t["catalog"].put_item(Item={**mm, "pk": f"MODEL#{mm['model_id']}", "sk": "META"})
        for i in load("seed/inventory.json"):
            t["inventory"].put_item(Item={**i, "pk": i["location_id"], "sk": i["component_id"]})
        for tech in load("seed/technicians.json"):
            t["technicians"].put_item(Item={**tech, "pk": f"TECH#{tech['technician_id']}", "sk": "META"})
        t["machine_state"].put_item(
            Item={
                "pk": "EX-023",
                "sk": "LAST",
                "reading": {"temperature_c": Decimal("98.4"), "vibration_mm_s": Decimal("7.2")},
            }
        )
        t["incidents"].put_item(
            Item={
                "pk": "INC#INC-01JC8ZK",
                "sk": "META",
                "incident_id": "INC-01JC8ZK",
                "machine_id": "EX-023",
                "machine_ids": ["EX-023"],
                "zone": "norte",
                "severity": "high",
                "status": "detected",
                "detected_at": "2026-11-13T10:15:00Z",
                "source": "anomaly",
            }
        )
        yield t


def meta(t):
    return t["incidents"].get_item(Key={"pk": "INC#INC-01JC8ZK", "sk": "META"})["Item"]


def ev(action, **kw):
    return {"action": action, "incident_id": "INC-01JC8ZK", "machine_id": "EX-023", "zone": "norte", **kw}


def test_contexto_arma_payload_de_diagnose(tables):
    req = load("ia/diagnose_request.json")["payload"]
    out = service.run(
        ev(
            "contexto",
            severity="high",
            health_score=42,
            top_factors=json.loads(json.dumps(req["top_factors"], default=float)),
        ),
        tables,
    )
    p = out["diagnose_payload"]
    assert p["model"] == "CAT-336" and p["machine_type"] == "excavator"
    assert p["candidate_parts"] == json.loads(json.dumps(req["candidate_parts"]))
    assert p["latest_reading"] == {"temperature_c": 98.4, "vibration_mm_s": 7.2}
    assert out["location"] == {"lat": -11.913239, "lon": -76.39975, "zone": "norte"}


def test_required_specialty_regla_8_2():
    cp = [{"component_id": "CMP-009", "specialty": "hidraulica"}]
    assert service.required_specialty("anomaly", [], ["CMP-009"], cp) == "hidraulica"
    assert service.required_specialty("anomaly", [{"variable": "pressure_bar", "z_score": -4}], [], cp) == "hidraulica"
    assert service.required_specialty("anomaly", [{"variable": "speed_kmh", "z_score": 2}], [], cp) == "neumaticos"
    assert service.required_specialty("silence", [], [], cp) == "electrica"
    assert service.required_specialty("anomaly", [], [], cp) == "motor"


def test_golden_path_completo(tables):
    req = load("ia/diagnose_request.json")["payload"]
    diag = json.loads((FIX / "ia/diagnose_response.json").read_text())
    factors = json.loads(json.dumps(req["top_factors"], default=float))
    cparts = json.loads(json.dumps(req["candidate_parts"]))
    out = service.run(
        ev(
            "enriquecer",
            source="anomaly",
            top_factors=factors,
            diagnosis=diag,
            candidate_parts=cparts,
            correlation={"parent_incident_id": None, "machines": ["EX-023"]},
            model_version="v1",
        ),
        tables,
    )
    assert out["required_specialty"] == "motor" and out["part_id"] == "CMP-014" and out["shortage"] is False
    item = meta(tables)
    assert item["ai_diagnosis"]["parts_suggested"] == ["CMP-014"] and item["required_specialty"] == "motor"

    scoring = json.loads((FIX / "internal/scoring_response.json").read_text())
    out = service.run(ev("asignar", technician_id="TEC-07", scoring=scoring), tables)
    assert out["from"] == "detected"
    item = meta(tables)
    assert item["status"] == "assigned" and item["technician_score"] == Decimal("0.98")
    assert len(item["scoring_candidates"]) == 3
    tech = tables["technicians"].get_item(Key={"pk": "TECH#TEC-07", "sk": "META"})["Item"]
    assert tech["current_load"] == 1

    service.run(ev("guardar_token", token_name="ack_token", token="T-ACK", statuses=["assigned"]), tables)
    assert meta(tables)["ack_token"] == "T-ACK"
    # la SFN acepta con UpdateItem directo
    tables["incidents"].update_item(
        Key={"pk": "INC#INC-01JC8ZK", "sk": "META"},
        UpdateExpression="SET #s = :p REMOVE ack_token",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":p": "in_progress"},
    )
    service.run(ev("guardar_token", token_name="resolve_token", token="T-RES", statuses=["in_progress"]), tables)

    out = service.run(
        ev(
            "resolver",
            resolution={
                "resolution_notes": "Cambio de rodamientos",
                "components_replaced": ["CMP-014"],
                "cost_usd": 820.5,
            },
        ),
        tables,
    )
    assert out["downtime_minutes"] >= 0
    item = meta(tables)
    assert item["status"] == "resolved" and "resolve_token" not in item and item["cost_usd"] == Decimal("820.5")

    stock_before = tables["inventory"].get_item(Key={"pk": "WH-01", "sk": "CMP-014"})["Item"]["stock"]
    out = service.run(
        ev("cerrar", summary={"result": {"summary": "Rodamientos reemplazados", "root_cause": "desgaste"}}), tables
    )
    item = meta(tables)
    assert item["status"] == "closed" and item["resolution_summary"] == "Rodamientos reemplazados"
    rec = tables["maintenance_records"].scan()["Items"][0]
    assert rec["type"] == "corrective" and rec["components"] == [{"component_id": "CMP-014", "quantity": 1}]
    assert rec["pk"] == "EX-023" and rec["record_id"] == "MR-01JC8ZK"
    assert tables["inventory"].get_item(Key={"pk": "WH-01", "sk": "CMP-014"})["Item"]["stock"] == stock_before - 1
    assert "open_incident_id" not in tables["machines"].get_item(Key={"pk": "OP-01#EX-023", "sk": "META"})["Item"]
    tech = tables["technicians"].get_item(Key={"pk": "TECH#TEC-07", "sk": "META"})["Item"]
    assert tech["current_load"] == 0
    # reintento del cierre es idempotente
    assert service.run(ev("cerrar", summary={}), tables)["from"] == "closed"


def test_reasignacion_mueve_la_carga(tables):
    service.run(ev("asignar", technician_id="TEC-07", scoring={"candidates": []}), tables)
    out = service.run(ev("asignar", technician_id="TEC-01", actor={"type": "user"}), tables)
    assert out["from"] == "assigned" and out["previous_technician_id"] == "TEC-07"
    loads = {
        t: tables["technicians"].get_item(Key={"pk": f"TECH#{t}", "sk": "META"})["Item"]["current_load"]
        for t in ("TEC-07", "TEC-01")
    }
    assert loads == {"TEC-07": 0, "TEC-01": 1}
    assert "technician_score" not in meta(tables)


def test_token_con_estado_incorrecto_falla(tables):
    with pytest.raises(service.ConditionFailed):
        service.run(ev("guardar_token", token_name="resolve_token", token="X", statuses=["in_progress"]), tables)


def test_accion_desconocida(tables):
    with pytest.raises(ValueError):
        service.run({"action": "borrar"}, tables)


def _resolved(tables):
    service.run(ev("asignar", technician_id="TEC-07", scoring={"candidates": []}), tables)
    tables["incidents"].update_item(
        Key={"pk": "INC#INC-01JC8ZK", "sk": "META"},
        UpdateExpression="SET #s = :p",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":p": "in_progress"},
    )
    service.run(ev("resolver", resolution={"resolution_notes": "ok", "components_replaced": ["CMP-014"]}), tables)


def test_cerrar_reintento_no_duplica_registro_ni_descuento(tables):
    """G-06: un Retry de la SFN tras fallo parcial no duplica maintenance-records ni descuenta dos veces."""
    _resolved(tables)
    stock = lambda: tables["inventory"].get_item(Key={"pk": "WH-01", "sk": "CMP-014"})["Item"]["stock"]  # noqa: E731
    before = stock()
    service.run(ev("cerrar", summary={}), tables)
    assert stock() == before - 1
    # simula fallo tras el descuento: el incidente vuelve a `resolved` y la SFN reintenta
    tables["incidents"].update_item(
        Key={"pk": "INC#INC-01JC8ZK", "sk": "META"},
        UpdateExpression="SET #s = :r",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":r": "resolved"},
    )
    out = service.run(ev("cerrar", summary={}), tables)
    assert out["from"] == "resolved"
    assert len(tables["maintenance_records"].scan()["Items"]) == 1
    assert stock() == before - 1
    assert meta(tables)["status"] == "closed" and meta(tables)["inventory_discounted"] is True


def test_abandonar_marca_borra_token_y_libera_despues(tables):
    service.run(ev("asignar", technician_id="TEC-07", scoring={"candidates": []}), tables)
    service.run(ev("guardar_token", token_name="ack_token", token="T", statuses=["assigned"]), tables)
    out = service.run(ev("abandonar", reason="manual_timeout"), tables)
    item = meta(tables)
    assert out["from"] == "assigned" and out["abandoned"] is True and out["released"] is True
    assert item["status"] == "abandoned" and "ack_token" not in item and item["abandon_reason"] == "manual_timeout"
    assert "open_incident_id" not in tables["machines"].get_item(Key={"pk": "OP-01#EX-023", "sk": "META"})["Item"]
    tech = tables["technicians"].get_item(Key={"pk": "TECH#TEC-07", "sk": "META"})["Item"]
    assert tech["current_load"] == 0
    assert service.run(ev("abandonar"), tables)["from"] == "abandoned"  # reintento idempotente


def test_abandonar_incidente_cerrado_falla(tables):
    _resolved(tables)
    service.run(ev("cerrar", summary={}), tables)
    with pytest.raises(service.ConditionFailed):
        service.run(ev("abandonar"), tables)
