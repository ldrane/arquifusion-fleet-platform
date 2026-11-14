import json
from pathlib import Path

import service

FIX = Path(__file__).parents[4] / "contracts" / "fixtures"


def load(rel):
    return json.loads((FIX / rel).read_text())


def techs_zone(zone):
    return [t for t in load("seed/technicians.json") if t["zone"] == zone]


def test_fixture_scoring_ex023_gana_tec07():
    req = load("internal/scoring_request.json")
    expected = load("internal/scoring_response.json")
    resp = service.run(req, {"load": techs_zone})
    assert resp["selected"] == expected["selected"] == "TEC-07"
    assert resp["weights"] == expected["weights"]
    got = {c["technician_id"]: c for c in resp["candidates"]}
    for exp in expected["candidates"]:
        assert got[exp["technician_id"]]["score"] == exp["score"]
        assert got[exp["technician_id"]]["eta_min"] == exp["eta_min"]
        assert got[exp["technician_id"]]["breakdown"] == exp["breakdown"]
    assert [c["technician_id"] for c in resp["candidates"]][:2] == ["TEC-07", "TEC-01"]


def test_rechazo_pasa_al_segundo():
    req = {**load("internal/scoring_request.json"), "exclude_technician_ids": ["TEC-07"]}
    assert service.run(req, {"load": techs_zone})["selected"] == "TEC-01"


def test_sin_candidatos_selected_null():
    req = load("internal/scoring_request.json")
    ids = [t["technician_id"] for t in techs_zone("norte")]
    resp = service.run({**req, "exclude_technician_ids": ids}, {"load": techs_zone})
    assert resp == {"selected": None, "weights": resp["weights"], "candidates": []}


def test_no_disponible_no_es_elegido():
    techs = [{**t, "available": t["technician_id"] != "TEC-07"} for t in techs_zone("norte")]
    resp = service.run(load("internal/scoring_request.json"), {"load": lambda z: techs})
    assert resp["selected"] != "TEC-07"


def test_sin_ubicacion_de_maquina_igual_puntua():
    req = {**load("internal/scoring_request.json"), "location": None}
    resp = service.run(req, {"load": techs_zone})
    assert resp["selected"] in {"TEC-07", "TEC-01"}
    assert all(c["eta_min"] == 45 for c in resp["candidates"])
