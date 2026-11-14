"""Tests de los seeds (sin AWS). Correr: python -m pytest scripts/tests -q"""

import re
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import seed  # noqa: E402
import seed_data  # noqa: E402

MACHINE_ID_RE = re.compile(r"^[A-Z]{2}-[0-9]{3,4}$")  # openapi.yaml TelemetryReading.machine_id
MACHINE_TYPES = {"excavator", "mining_truck", "loader", "bulldozer", "drill"}
SPECIALTIES = {"motor", "hidraulica", "electrica", "neumaticos"}
SEVERITIES = {"info", "low", "medium", "high", "critical"}
ROLES = {"operador", "tecnico", "mantenimiento", "supervisor", "admin", "gerencia"}
MACHINE_STATUSES = {"operational", "stopped", "maintenance", "needs_intervention", "silent"}  # MachineStatus


def test_determinista():
    assert seed_data.build_all() == seed_data.build_all()


def test_cantidades_requerimientos_5_6():
    data = seed_data.build_all()
    assert 50 <= len(data["machines"]) <= 100
    assert {m["type"] for m in data["machines"]} == MACHINE_TYPES
    assert 3 <= len({m["zone"] for m in data["machines"]}) <= 5
    assert len(data["technicians"]) >= 10
    assert 20 <= len(data["catalog"]) <= 30
    # requerimientos §5.6 pide 2-3 almacenes; seed v2 agrega WH-04 para que la zona oeste (32 máquinas) tenga uno (#19)
    assert 2 <= len(data["warehouses"]) <= 4
    assert {w["zone"] for w in data["warehouses"]} == set(seed_data.ZONES)


def test_ids_de_los_contratos_existen():
    data = seed_data.build_all()
    ex023 = next(m for m in data["machines"] if m["machine_id"] == "EX-023")
    assert ex023["zone"] == "norte" and ex023["model"] == "CAT-336" and ex023["type"] == "excavator"
    assert any(t["technician_id"] == "TEC-07" for t in data["technicians"])
    assert any(c["component_id"] == "CMP-014" for c in data["catalog"])
    assert any(i["warehouse_id"] == "WH-01" for i in data["inventory"])


def test_maquinas_respetan_schema_openapi():
    for m in seed_data.build_all()["machines"]:
        assert MACHINE_ID_RE.match(m["machine_id"]), m["machine_id"]
        assert m["type"] in MACHINE_TYPES
        assert m["status"] in MACHINE_STATUSES and m["severity"] in SEVERITIES
        assert 0 <= m["health_score"] <= 100
        assert -90 <= m["location"]["lat"] <= 90 and -180 <= m["location"]["lon"] <= 180
        assert m["location"]["zone"] == m["zone"]


def test_ids_unicos():
    data = seed_data.build_all()
    for dataset, field in [("machines", "machine_id"), ("technicians", "technician_id"), ("catalog", "component_id")]:
        ids = [r[field] for r in data[dataset]]
        assert len(ids) == len(set(ids)), dataset


def test_enums_de_tecnicos_reglas_e_inventario():
    data = seed_data.build_all()
    for t in data["technicians"]:
        assert set(t["specialties"]) <= SPECIALTIES and t["shift"] in {"day", "night"}
    for r in data["notification_rules"]:
        assert r["role"] in ROLES and r["severity_min"] in SEVERITIES
    alerts = {i["alert"] for i in data["inventory"]}
    assert alerts == {"none", "low_stock", "overstock"}  # la demo muestra los 3 casos
    golden = next(i for i in data["inventory"] if (i["warehouse_id"], i["component_id"]) == ("WH-01", "CMP-014"))
    assert golden["stock"] >= golden["stock_min"]  # el golden path tiene repuesto


def test_claves_unicas_por_tabla():
    data = seed_data.build_all()
    seen: dict[str, set] = {}
    for dataset in seed.KEY_SCHEMA:
        table = seed.KEY_SCHEMA[dataset]["table"]
        for rec in data[dataset]:
            item = seed.to_item(dataset, rec)
            key = (item["pk"], item["sk"])
            assert key not in seen.setdefault(table, set()), (dataset, key)
            seen[table].add(key)


def test_to_item_convierte_float_a_decimal():
    rec = seed_data.build_all()["machines"][0]
    item = seed.to_item("machines", rec)
    assert item["pk"] == f"OP-01#{rec['machine_id']}" and item["sk"] == "META"
    assert isinstance(item["location"]["lat"], Decimal)


class _CondFail(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTable:
    """Imita put_item condicional de DynamoDB."""

    def __init__(self):
        self.items = {}

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeNames=None):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression and key in self.items:
            raise _CondFail()
        self.items[key] = Item


def test_load_es_idempotente():
    table = FakeTable()
    records = seed_data.build_all()["machines"]
    assert seed.put_records(table, "machines", records, force=False) == (len(records), 0)
    assert seed.put_records(table, "machines", records, force=False) == (0, len(records))
    assert seed.put_records(table, "machines", records, force=True) == (len(records), 0)
    assert len(table.items) == len(records)


def test_claves_segun_contrato_seccion_9():
    data = seed_data.build_all()
    ex = next(m for m in data["machines"] if m["machine_id"] == "EX-023")
    assert seed.to_item("machines", ex)["pk"] == "OP-01#EX-023"
    inv = next(i for i in data["inventory"] if (i["warehouse_id"], i["component_id"]) == ("WH-01", "CMP-014"))
    item = seed.to_item("inventory", inv)
    assert (item["pk"], item["sk"], item["location_id"]) == ("WH-01", "CMP-014", "WH-01")
    assert "cost_usd" in data["catalog"][0]


def test_to_item_omite_nulls():
    """Un atributo NULL cuenta como existente en DynamoDB: rompería heartbeat y el dedup de procesar (A)."""
    for record in seed_data.build_all()["machines"]:
        item = seed.to_item("machines", record)
        assert None not in item.values()
        assert "last_seen_at" not in item and "open_incident_id" not in item


# --------------------------------------------------------------------------- seed v4: variedad
def test_variedad_de_modelos_marcas_y_zonas():
    data = seed_data.build_all()
    machines, models = data["machines"], {m["model_id"]: m for m in data["machine_models"]}
    assert {m["model"] for m in machines} == set(models)  # todos los modelos tienen al menos una máquina
    assert len({m["brand"] for m in models.values()}) >= 6
    for t in MACHINE_TYPES:
        assert len({m["model"] for m in machines if m["type"] == t}) >= 3, t
        assert all(models[m["model"]]["type"] == m["type"] for m in machines)
    # la distribución por zona depende del tipo (no es uniforme): la perforación se concentra en el este
    drills = [m for m in machines if m["type"] == "drill"]
    assert sum(m["zone"] == "este" for m in drills) > len(drills) / 2
    hours = [m["operating_hours"] for m in machines]
    assert min(hours) < 1500 and max(hours) > 20000
    assert len({m["health_score"] for m in machines}) >= 15


def test_estados_iniciales_variados_y_coherentes():
    machines = seed_data.build_all()["machines"]
    statuses = {m["status"] for m in machines}
    assert {"operational", "maintenance", "stopped"} <= statuses
    assert sum(m["status"] == "operational" for m in machines) >= 85  # la demo necesita flota operando
    for m in machines:
        if m["status"] == "maintenance":  # en taller por el preventivo vencido
            assert m["next_maintenance_at"] < seed_data.REFERENCE_DATE.isoformat()
    pinned = {m["machine_id"]: m for m in machines if m["machine_id"] in seed_data.PINNED_MACHINES}
    assert all(m["status"] == "operational" for m in pinned.values())


def test_catalogo_e_inventario_cubren_todos_los_modelos():
    data = seed_data.build_all()
    catalog_ids = {c["component_id"] for c in data["catalog"]}
    for model in data["machine_models"]:
        assert len(model["component_ids"]) >= 15, model["model_id"]
        assert set(model["component_ids"]) <= catalog_ids
    inv = {(i["warehouse_id"], i["component_id"]) for i in data["inventory"]}
    assert inv == {(w["warehouse_id"], c) for w in data["warehouses"] for c in catalog_ids}
    lows = [i for i in data["inventory"] if i["alert"] == "low_stock"]
    overs = [i for i in data["inventory"] if i["alert"] == "overstock"]
    assert len(lows) >= 5 and len(overs) >= 4
    assert len({i["warehouse_id"] for i in lows}) >= 3  # quiebres repartidos en varios almacenes


def test_cat336_del_golden_path_no_cambia_de_repuestos():
    """diagnose_request.json (W1/ia) lista MODEL#CAT-336.component_ids: los repuestos v4 no aplican al CAT-336."""
    cat336 = next(m for m in seed_data.build_all()["machine_models"] if m["model_id"] == "CAT-336")
    assert cat336["component_ids"] == [f"CMP-{i:03d}" for i in list(range(1, 21)) + [23]]


def test_tecnicos_variados_sin_tocar_la_zona_del_golden_path():
    techs = seed_data.build_all()["technicians"]
    assert len({t["shift"] for t in techs}) == 2
    assert any(not t["available"] for t in techs) and any(t["current_load"] > 0 for t in techs)
    assert any(len(t["specialties"]) == 3 for t in techs)
    for t in techs:
        if t["zone"] == "norte":  # scoring_response.json: TEC-07 0.98 y TEC-01 2.º, todos disponibles y sin carga
            assert t["available"] and t["current_load"] == 0
    for zone in seed_data.ZONES:
        assert any(t["zone"] == zone and t["available"] and t["shift"] == "day" for t in techs), zone
