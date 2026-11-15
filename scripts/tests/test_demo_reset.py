"""Tests de `scripts/demo_reset.py` (TAREA-18) con moto (DynamoDB) y un fake de Step Functions / SSM."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import demo_reset  # noqa: E402


# --------------------------------------------------------------------------- fakes
class FakeSfn:
    def __init__(self, existing: set[str] | None = None):
        self.existing = existing if existing is not None else None  # None = todas existen
        self.stopped: list[dict] = []

    def stop_execution(self, executionArn: str, error: str, cause: str):  # noqa: N803 (nombre del SDK)
        if self.existing is not None and executionArn not in self.existing:
            raise ClientError(
                {"Error": {"Code": "ExecutionDoesNotExist", "Message": "no existe"}}, "StopExecution"
            )
        self.stopped.append({"arn": executionArn, "error": error, "cause": cause})


class FakeSsm:
    def __init__(self, state: dict | None = None):
        self.values: dict[str, str] = {} if state is None else {"/arquifusion/dev/sim/state": json.dumps(state)}
        self.puts: list[dict] = []

    def get_parameter(self, Name: str):  # noqa: N803
        if Name not in self.values:
            raise ClientError({"Error": {"Code": "ParameterNotFound", "Message": "no existe"}}, "GetParameter")
        return {"Parameter": {"Value": self.values[Name]}}

    def put_parameter(self, Name: str, Value: str, Type: str, Overwrite: bool):  # noqa: N803
        self.values[Name] = Value
        self.puts.append({"name": Name, "value": Value})


# --------------------------------------------------------------------------- DynamoDB
def _tables():
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    incidents = ddb.create_table(
        TableName="arquifusion-dev-incidents",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "detected_at", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
        GlobalSecondaryIndexes=[
            {
                "IndexName": "by_status",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "detected_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )
    machines = ddb.create_table(
        TableName="arquifusion-dev-machines",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
            {"AttributeName": "zone", "AttributeType": "S"},
            {"AttributeName": "machine_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
        GlobalSecondaryIndexes=[
            {
                "IndexName": "by_zone",
                "KeySchema": [
                    {"AttributeName": "zone", "KeyType": "HASH"},
                    {"AttributeName": "machine_id", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
    )
    technicians = ddb.create_table(
        TableName="arquifusion-dev-technicians",
        KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    return incidents, machines, technicians


def _seed(incidents, machines, technicians):
    incidents.put_item(
        Item={
            "pk": "INC#INC-01",
            "sk": "META",
            "incident_id": "INC-01",
            "machine_id": "EX-023",
            "machine_ids": ["EX-023"],
            "zone": "norte",
            "status": "assigned",
            "severity": "high",
            "detected_at": "2026-11-14T10:00:00Z",
            "ack_token": "SECRETO",
            "resolve_token": "SECRETO2",
            "execution_arn": "arn:aws:states:us-east-1:000000000000:execution:sfn:run-1",
        }
    )
    incidents.put_item(
        Item={
            "pk": "INC#INC-02",
            "sk": "META",
            "incident_id": "INC-02",
            "machine_id": "EX-001",
            "machine_ids": ["EX-001"],
            "zone": "sur",
            "status": "closed",
            "severity": "critical",
            "detected_at": "2026-11-13T08:00:00Z",
        }
    )
    machines.put_item(Item={"pk": "OP-01#EX-023", "sk": "META", "machine_id": "EX-023", "zone": "norte",
                            "open_incident_id": "INC-01"})
    machines.put_item(Item={"pk": "OP-01#EX-001", "sk": "META", "machine_id": "EX-001", "zone": "sur"})
    technicians.put_item(Item={"pk": "TECH#TEC-07", "sk": "META", "technician_id": "TEC-07", "zone": "norte",
                               "current_load": 2, "available": False})
    technicians.put_item(Item={"pk": "TECH#TEC-02", "sk": "META", "technician_id": "TEC-02", "zone": "sur",
                               "current_load": 0, "available": True})


# --------------------------------------------------------------------------- tests
@mock_aws
def test_list_open_incidents_excluye_cerrados_y_abandonados():
    incidents, machines, technicians = _tables()
    _seed(incidents, machines, technicians)
    abiertos = demo_reset.list_open_incidents(incidents)
    assert [i["incident_id"] for i in abiertos] == ["INC-01"]  # INC-02 está closed


@mock_aws
def test_reset_abandona_detiene_maquina_tecnico_y_simulador():
    incidents, machines, technicians = _tables()
    _seed(incidents, machines, technicians)
    sfn, ssm = FakeSfn(), FakeSsm({"enabled": True, "scenario": "falla_subita"})
    deps = {"incidents": incidents, "machines": machines, "technicians": technicians, "sfn": sfn, "ssm": ssm,
            "stage": "dev", "now": lambda: "2026-11-15T12:00:00Z"}

    result = demo_reset.reset(deps, demo_reset.list_open_incidents(incidents))

    assert result == {
        "stopped_executions": 1,
        "abandoned_incidents": 1,
        "cleared_machines": 1,
        "reset_technicians": 2,
        "simulator_off": True,
    }
    # detuvo la ejecución de la SFN
    assert sfn.stopped == [
        {
            "arn": "arn:aws:states:us-east-1:000000000000:execution:sfn:run-1",
            "error": "DemoReset",
            "cause": "reset_by_demo",
        }
    ]
    # incidente abandonado, con marca de reset y sin tokens secretos
    inc = incidents.get_item(Key={"pk": "INC#INC-01", "sk": "META"})["Item"]
    assert inc["status"] == "abandoned" and inc["reset_by_demo"] is True
    assert inc["abandoned_at"] == "2026-11-15T12:00:00Z"
    assert "ack_token" not in inc and "resolve_token" not in inc
    # la máquina ya no tiene el lock
    assert "open_incident_id" not in machines.get_item(Key={"pk": "OP-01#EX-023", "sk": "META"})["Item"]
    # técnicos liberados
    for pk in ("TECH#TEC-07", "TECH#TEC-02"):
        t = technicians.get_item(Key={"pk": pk, "sk": "META"})["Item"]
        assert int(t["current_load"]) == 0 and t["available"] is True
    # simulador apagado conservando el resto del estado
    assert json.loads(ssm.values["/arquifusion/dev/sim/state"]) == {"enabled": False, "scenario": "falla_subita"}


@mock_aws
def test_reset_ignora_ejecucion_inexistente():
    incidents, machines, technicians = _tables()
    _seed(incidents, machines, technicians)
    sfn = FakeSfn(existing=set())  # ninguna ejecución existe ya
    ssm = FakeSsm()  # sin parámetro de simulador
    deps = {"incidents": incidents, "machines": machines, "technicians": technicians, "sfn": sfn, "ssm": ssm,
            "stage": "dev"}

    result = demo_reset.reset(deps, demo_reset.list_open_incidents(incidents))

    assert result["stopped_executions"] == 0 and result["abandoned_incidents"] == 1
    assert result["simulator_off"] is False  # no había parámetro
    assert incidents.get_item(Key={"pk": "INC#INC-01", "sk": "META"})["Item"]["status"] == "abandoned"


@mock_aws
def test_plan_es_solo_lectura():
    incidents, machines, technicians = _tables()
    _seed(incidents, machines, technicians)
    abiertos = demo_reset.list_open_incidents(incidents)
    tecnicos = demo_reset.list_technicians(technicians)
    plan = demo_reset.build_plan(abiertos, tecnicos, True)
    assert plan["open_incidents"][0]["incident_id"] == "INC-01" and plan["open_incidents"][0]["has_execution"] is True
    assert plan["technicians_with_load"] == [{"technician_id": "TEC-07", "current_load": 2}]
    assert plan["simulator_enabled"] is True
    # no mutó nada
    assert incidents.get_item(Key={"pk": "INC#INC-01", "sk": "META"})["Item"]["status"] == "assigned"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
