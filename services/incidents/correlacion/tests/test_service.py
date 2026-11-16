import json
from pathlib import Path

import service

FIX = Path(__file__).parents[4] / "contracts" / "fixtures" / "internal"


class FakeRepo:
    def __init__(self, machines, incidents=None):
        self.machines = machines
        self.incidents = incidents or {}
        self.links = []
        self.window = None

    def machines_in_window(self, zone, start, end):
        self.window = (zone, start, end)
        return list(self.machines)

    def latest_incident(self, machine_id):
        return self.incidents.get(machine_id)

    def link_child(self, parent_id, child_id, machine_id):
        self.links.append((parent_id, child_id, machine_id))
        return parent_id


class RejectingRepo(FakeRepo):
    """Simula la carrera: ese padre dejó de ser elegible antes de enlazar."""

    def link_child(self, parent_id, child_id, machine_id):
        if parent_id in self.rejected:
            raise service.LinkRejected(parent_id)
        return super().link_child(parent_id, child_id, machine_id)

    def __init__(self, machines, incidents=None, rejected=()):
        super().__init__(machines, incidents)
        self.rejected = set(rejected)


def test_fixture_sin_correlacion():
    req = json.loads((FIX / "correlacion_request.json").read_text())
    expected = json.loads((FIX / "correlacion_response.json").read_text())
    repo = FakeRepo(["EX-023"])
    assert service.run(req, repo) == expected
    assert repo.window == ("norte", "2026-11-13T09:59:55Z", "2026-11-13T10:14:56Z")


def test_tres_maquinas_enlaza_al_padre_mas_antiguo():
    incidents = {
        "EX-010": {"incident_id": "INC-B", "status": "assigned", "detected_at": "2026-11-13T10:05:00Z"},
        "EX-011": {"incident_id": "INC-A", "status": "detected", "detected_at": "2026-11-13T10:01:00Z"},
    }
    repo = FakeRepo(["EX-010", "EX-011", "EX-023"], incidents)
    req = {"incident_id": "INC-C", "machine_id": "EX-023", "zone": "norte", "reading_ts": "2026-11-13T10:14:55Z"}
    resp = service.run(req, repo)
    assert resp == {"parent_incident_id": "INC-A", "machines": ["EX-023", "EX-010", "EX-011"]}
    assert repo.links == [("INC-A", "INC-C", "EX-023")]


def test_tres_maquinas_sin_incidentes_abiertos_queda_como_padre():
    incidents = {"EX-010": {"incident_id": "INC-Z", "status": "closed", "detected_at": "2026-11-13T10:05:00Z"}}
    repo = FakeRepo(["EX-010", "EX-011"], incidents)
    req = {"incident_id": "INC-C", "machine_id": "EX-023", "zone": "norte", "reading_ts": "2026-11-13T10:14:55Z"}
    resp = service.run(req, repo)
    assert resp["parent_incident_id"] is None
    assert resp["machines"][0] == "EX-023" and len(resp["machines"]) == 3


def test_si_el_padre_deja_de_ser_elegible_prueba_el_siguiente():
    """Carrera: el más antiguo ya se enlazó como hijo → se usa el siguiente candidato abierto."""
    incidents = {
        "EX-010": {"incident_id": "INC-A", "status": "assigned", "detected_at": "2026-11-13T10:01:00Z"},
        "EX-011": {"incident_id": "INC-B", "status": "detected", "detected_at": "2026-11-13T10:05:00Z"},
    }
    repo = RejectingRepo(["EX-010", "EX-011"], incidents, rejected=["INC-A"])
    req = {"incident_id": "INC-C", "machine_id": "EX-023", "zone": "norte", "reading_ts": "2026-11-13T10:14:55Z"}
    resp = service.run(req, repo)
    assert resp["parent_incident_id"] == "INC-B"
    assert repo.links == [("INC-B", "INC-C", "EX-023")]


def test_si_ningun_candidato_acepta_queda_como_padre():
    """Sin enlace posible, el incidente queda raíz (nunca sin padre y sin grupo)."""
    incidents = {
        "EX-010": {"incident_id": "INC-A", "status": "assigned", "detected_at": "2026-11-13T10:01:00Z"},
        "EX-011": {"incident_id": "INC-B", "status": "detected", "detected_at": "2026-11-13T10:05:00Z"},
    }
    repo = RejectingRepo(["EX-010", "EX-011"], incidents, rejected=["INC-A", "INC-B"])
    req = {"incident_id": "INC-C", "machine_id": "EX-023", "zone": "norte", "reading_ts": "2026-11-13T10:14:55Z"}
    resp = service.run(req, repo)
    assert resp["parent_incident_id"] is None
    assert repo.links == []
