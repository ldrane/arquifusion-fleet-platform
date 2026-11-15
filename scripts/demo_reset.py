#!/usr/bin/env python3
"""Reset de la demo (TAREA-18): deja la flota limpia entre ensayos, sin borrar nada (append-only).

Problema: el lock `open_incident_id` de `machines` y los incidentes abiertos se acumulan entre ensayos,
y la SFN puede quedar esperando un `ack`/`resolve` que ya nadie hará.

Qué hace con `--yes` (por incidente abierto: `status` != `closed`/`abandoned`):
  1. `stop_execution` de su `execution_arn` (si existe), para que no siga la espera por `task token`.
  2. marca el incidente `abandoned` con `reset_by_demo=true` (no se borra: el ledger es append-only).
  3. limpia `open_incident_id` de la máquina (solo si seguía apuntando a este incidente).
  Además: `current_load=0` y `available=true` en todos los técnicos, y apaga el simulador serverless (SSM).
Sin `--yes` solo imprime el plan (dry-run).

Uso (desde la raíz del repo, con credenciales del lab):
  python3 scripts/demo_reset.py --stage dev            # dry-run (no cambia nada)
  python3 scripts/demo_reset.py --stage dev --yes      # aplica
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from functools import partial
from typing import Any

OPEN_STATUSES = ("detected", "assigned", "in_progress", "resolved")
CLOSED_STATUSES = ("closed", "abandoned")  # para documentar el criterio de "abierto"
DEFAULT_REGION = "us-east-1"

Table = Any


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def table_name(stage: str, name: str) -> str:
    """Nombre físico de una tabla: `TABLE_<NAME>` si está en el entorno, si no `arquifusion-<stage>-<name>`."""
    return os.environ.get("TABLE_" + name.replace("-", "_").upper()) or f"arquifusion-{stage}-{name}"


def _all(query: Callable[..., dict]) -> list[dict]:
    """Recorre todas las páginas de un `query`/`scan` de DynamoDB."""
    items: list[dict] = []
    kwargs: dict[str, Any] = {}
    while True:
        page = query(**kwargs)
        items.extend(page.get("Items", []))
        last = page.get("LastEvaluatedKey")
        if not last:
            return items
        kwargs["ExclusiveStartKey"] = last


def list_open_incidents(incidents: Table) -> list[dict]:
    """Incidentes con `status` abierto (GSI `by_status`), ordenados por `detected_at`."""
    from boto3.dynamodb.conditions import Key

    by_id: dict[str, dict] = {}
    for status in OPEN_STATUSES:
        condition = Key("status").eq(status)
        query = partial(incidents.query, IndexName="by_status", KeyConditionExpression=condition)
        for item in _all(query):
            if item.get("sk") == "META":
                by_id[item["incident_id"]] = item
    return sorted(by_id.values(), key=lambda i: i.get("detected_at") or "")


def list_technicians(technicians: Table) -> list[dict]:
    return [t for t in _all(technicians.scan) if t.get("sk") == "META"]


def _machine_key(machines: Table, machine_id: str, zone: str | None) -> dict | None:
    """Localiza la clave `{operation_id}#{machine_id}` de una máquina por el GSI `by_zone`."""
    from boto3.dynamodb.conditions import Key

    condition = Key("zone").eq(zone) & Key("machine_id").eq(machine_id) if zone else Key("machine_id").eq(machine_id)
    try:
        page = machines.query(IndexName="by_zone", KeyConditionExpression=condition)
    except Exception:  # noqa: BLE001 (zona ausente: se recurre al scan)
        page = {}
    found = next((i for i in page.get("Items", []) if i.get("machine_id") == machine_id), None)
    if found is None:  # fallback: scan puntual (pocas máquinas: ~100)
        found = next((i for i in _all(machines.scan) if i.get("machine_id") == machine_id), None)
    return {"pk": found["pk"], "sk": "META"} if found else None


def _stop_execution(sfn: Any, arn: str | None) -> bool:
    if not arn or arn == "-":
        return False
    try:
        sfn.stop_execution(executionArn=arn, error="DemoReset", cause="reset_by_demo")
        return True
    except Exception as exc:  # noqa: BLE001 (execución ya terminada o inexistente)
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        if code in {"ExecutionDoesNotExist", "InvalidArn"}:
            return False
        raise


def reset(deps: dict, incidents: list[dict]) -> dict:
    """Aplica el reset sobre `incidents` (ya listados) y devuelve el resumen de lo cambiado."""
    sfn = deps["sfn"]
    incidents_table = deps["incidents"]
    machines = deps["machines"]
    technicians = deps["technicians"]
    ssm = deps["ssm"]
    stage = deps["stage"]
    at = deps.get("now", now_iso)()

    stopped, abandoned, cleared = 0, 0, 0
    for inc in incidents:
        if _stop_execution(sfn, inc.get("execution_arn")):
            stopped += 1
        incidents_table.update_item(
            Key={"pk": f"INC#{inc['incident_id']}", "sk": "META"},
            UpdateExpression=(
                "SET #st = :ab, abandoned_at = :at, abandon_reason = :why, reset_by_demo = :true "
                "REMOVE ack_token, resolve_token"
            ),
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":ab": "abandoned", ":at": at, ":why": "reset_by_demo", ":true": True},
        )
        abandoned += 1
        machine_ids = inc.get("machine_ids") or ([inc["machine_id"]] if inc.get("machine_id") else [])
        for machine_id in machine_ids:
            key = _machine_key(machines, machine_id, inc.get("zone"))
            if not key:
                continue
            try:
                machines.update_item(
                    Key=key,
                    UpdateExpression="REMOVE open_incident_id",
                    ConditionExpression="open_incident_id = :id",
                    ExpressionAttributeValues={":id": inc["incident_id"]},
                )
                cleared += 1
            except Exception as exc:  # noqa: BLE001 (ya no apuntaba a este incidente)
                if getattr(exc, "response", {}).get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                    raise

    technicians_reset = 0
    for tech in list_technicians(technicians):
        technicians.update_item(
            Key={"pk": tech["pk"], "sk": tech["sk"]},
            UpdateExpression="SET current_load = :z, available = :t",
            ExpressionAttributeValues={":z": 0, ":t": True},
        )
        technicians_reset += 1

    simulator_off = _turn_off_simulator(ssm, stage)

    return {
        "stopped_executions": stopped,
        "abandoned_incidents": abandoned,
        "cleared_machines": cleared,
        "reset_technicians": technicians_reset,
        "simulator_off": simulator_off,
    }


def _turn_off_simulator(ssm: Any, stage: str) -> bool:
    param = f"/arquifusion/{stage}/sim/state"
    try:
        raw = ssm.get_parameter(Name=param).get("Parameter", {}).get("Value") or "{}"
        state = json.loads(raw)
    except Exception as exc:  # noqa: BLE001 (parámetro ausente: no hay nada que apagar)
        if getattr(exc, "response", {}).get("Error", {}).get("Code") == "ParameterNotFound":
            return False
        raise
    if not state.get("enabled"):
        return False
    state["enabled"] = False
    ssm.put_parameter(Name=param, Value=json.dumps(state), Type="String", Overwrite=True)
    return True


def build_plan(open_incidents: list[dict], technicians: list[dict], sim_enabled: bool) -> dict:
    """Resumen de solo lectura para el dry-run."""
    return {
        "open_incidents": [
            {
                "incident_id": i["incident_id"],
                "machine_id": i.get("machine_id"),
                "status": i.get("status"),
                "severity": i.get("severity"),
                "has_execution": bool(i.get("execution_arn") and i.get("execution_arn") != "-"),
            }
            for i in open_incidents
        ],
        "technicians_with_load": [
            {"technician_id": t.get("technician_id"), "current_load": t.get("current_load")}
            for t in technicians
            if t.get("current_load")
        ],
        "simulator_enabled": sim_enabled,
    }


def _sim_enabled(ssm: Any, stage: str) -> bool:
    try:
        raw = ssm.get_parameter(Name=f"/arquifusion/{stage}/sim/state").get("Parameter", {}).get("Value") or "{}"
        return bool(json.loads(raw).get("enabled"))
    except Exception:  # noqa: BLE001
        return False


def _default_deps(stage: str, region: str) -> dict:  # pragma: no cover (requiere AWS)
    import boto3

    ddb = boto3.resource("dynamodb", region_name=region)
    return {
        "incidents": ddb.Table(table_name(stage, "incidents")),
        "machines": ddb.Table(table_name(stage, "machines")),
        "technicians": ddb.Table(table_name(stage, "technicians")),
        "sfn": boto3.client("stepfunctions", region_name=region),
        "ssm": boto3.client("ssm", region_name=region),
        "stage": stage,
    }


def _print_plan(plan: dict) -> None:
    incidents: Iterable[dict] = plan["open_incidents"]
    print(f"Incidentes abiertos: {len(plan['open_incidents'])}")
    for i in incidents:
        arn = "con execution_arn" if i["has_execution"] else "sin execution_arn"
        cols = f"{i['incident_id']:<12} {i['machine_id'] or '?':<10} {i['status']:<12} {i['severity'] or '':<9}"
        print(f"  - {cols} {arn}")
    print(f"Técnicos con carga: {len(plan['technicians_with_load'])}")
    for t in plan["technicians_with_load"]:
        print(f"  - {t['technician_id']}: current_load={t['current_load']}")
    print(f"Simulador: {'ENCENDIDO' if plan['simulator_enabled'] else 'apagado'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset de la demo (TAREA-18)")
    parser.add_argument("--stage", required=True, help="dev o la inicial de tu lab (p. ej. c)")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", DEFAULT_REGION))
    parser.add_argument("--yes", action="store_true", help="aplica los cambios (sin esto: dry-run)")
    args = parser.parse_args(argv)

    deps = _default_deps(args.stage, args.region)
    open_incidents = list_open_incidents(deps["incidents"])
    technicians = list_technicians(deps["technicians"])
    plan = build_plan(open_incidents, technicians, _sim_enabled(deps["ssm"], args.stage))
    _print_plan(plan)

    if not args.yes:
        print("\nDry-run: vuelve a correr con --yes para aplicar.")
        return 0

    result = reset(deps, open_incidents)
    print("\nAplicado:", json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
