"""Regresión RF-12.1: dos correlaciones simultáneas no pueden enlazarse mutuamente (ciclo).

Bug visto en producción: todos los incidentes abiertos tenían `parent_incident_id`, así que el front
(una tarjeta por grupo) mostraba 0 abiertos. La causa era la carrera entre correlaciones que se leían
"sin padre" a la vez; el `parent_incident_id` lo escribía `incidente` después, en otra escritura.
`Repo.link_child` ahora lo enlaza en una transacción con `attribute_not_exists(parent_incident_id)`
en el hijo y en el padre, así que la segunda correlación se cancela (queda como padre) y no hay ciclo.
"""

import boto3
import pytest
import service
from moto import mock_aws

TABLE = "t-incidents"


def _item(incident_id: str, detected_at: str, machine_id: str = "EX-001") -> dict:
    # Mismo ítem que crea la SFN (`CrearIncidente`): sin `parent_incident_id` (eso es justo lo que exige la condición).
    return {
        "pk": f"INC#{incident_id}",
        "sk": "META",
        "entity": "incident",
        "incident_id": incident_id,
        "machine_id": machine_id,
        "machine_ids": [machine_id],
        "child_incident_ids": [],
        "zone": "norte",
        "severity": "high",
        "status": "assigned",
        "detected_at": detected_at,
        "escalated": False,
        "is_recurrence": False,
    }


@pytest.fixture
def repo():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE,
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table = ddb.Table(TABLE)
        table.put_item(Item=_item("INC-A", "2026-11-15T22:32:35Z", "EX-A"))
        table.put_item(Item=_item("INC-B", "2026-11-15T22:33:00Z", "EX-B"))
        yield service.Repo(anomalies=None, incidents=table), table


def _incidents(table) -> dict:
    return {i["incident_id"]: i for i in table.scan()["Items"]}


def test_dos_correlaciones_cruzadas_no_forman_ciclo(repo):
    r, table = repo
    # Ambas ejecuciones leyeron candidatos antes de enlazar: A eligió a B y B eligió a A (la carrera).
    assert r.link_child("INC-B", "INC-A", "EX-A") == "INC-B"
    with pytest.raises(service.LinkRejected):
        r.link_child("INC-A", "INC-B", "EX-B")

    items = _incidents(table)
    assert items["INC-A"]["parent_incident_id"] == "INC-B"
    assert not items["INC-B"].get("parent_incident_id")  # B queda raíz: sin padre
    assert items["INC-B"]["child_incident_ids"] == ["INC-A"]
    assert items["INC-A"]["child_incident_ids"] == []


def test_no_forma_ciclo_en_el_orden_contrario(repo):
    r, table = repo
    assert r.link_child("INC-A", "INC-B", "EX-B") == "INC-A"
    with pytest.raises(service.LinkRejected):
        r.link_child("INC-B", "INC-A", "EX-A")

    items = _incidents(table)
    assert items["INC-B"]["parent_incident_id"] == "INC-A"
    assert not items["INC-A"].get("parent_incident_id")
    assert items["INC-A"]["child_incident_ids"] == ["INC-B"]


def test_reintento_del_mismo_enlace_es_idempotente(repo):
    r, table = repo
    assert r.link_child("INC-B", "INC-A", "EX-A") == "INC-B"
    # La SFN reintenta la tarea: devuelve el padre ya guardado y no duplica en child_incident_ids.
    assert r.link_child("INC-B", "INC-A", "EX-A") == "INC-B"
    items = _incidents(table)
    assert items["INC-B"]["child_incident_ids"] == ["INC-A"]
    assert items["INC-A"]["parent_incident_id"] == "INC-B"


def test_un_padre_que_ya_es_hijo_no_recibe_mas_hijos(repo):
    """Invariante: un hijo nunca es padre de otro (evita cadenas y ciclos)."""
    r, table = repo
    assert r.link_child("INC-B", "INC-A", "EX-A") == "INC-B"
    # C intenta enlazarse a A, que ya es hijo de B → rechazado.
    table.put_item(Item=_item("INC-C", "2026-11-15T22:34:00Z", "EX-C"))
    with pytest.raises(service.LinkRejected):
        r.link_child("INC-A", "INC-C", "EX-C")
    items = _incidents(table)
    assert items["INC-A"]["child_incident_ids"] == []
    assert not items["INC-C"].get("parent_incident_id")


def test_el_hijo_inexistente_no_se_enlaza(repo):
    r, table = repo
    with pytest.raises(service.LinkRejected):
        r.link_child("INC-B", "INC-FANTASMA", "EX-X")
    assert _incidents(table)["INC-B"]["child_incident_ids"] == []
