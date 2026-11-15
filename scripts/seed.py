#!/usr/bin/env python3
"""Seeds idempotentes de ArquiFusion (C1) — dueña: Persona C.

Uso (desde la raíz del repo):
  python scripts/seed.py export                       # genera contracts/fixtures/seed/*.json (sin AWS)
  python scripts/seed.py load   --stage dev           # carga en arquifusion-dev-* (solo crea lo que falta)
  python scripts/seed.py load   --stage dev --force   # sobrescribe (¡resetea status/health de la flota!)
  python scripts/seed.py verify --stage dev           # cuenta ítems y revisa los IDs de los contratos
  python scripts/seed.py reset-baselines --stage dev  # borra los BASELINE de machine-state (tras cambiar modelos/zonas)
  python scripts/seed.py load   --stage c --bootstrap-tables   # SOLO en tu lab personal: crea tablas temporales

Idempotencia: cada ítem se escribe con PutItem condicional (attribute_not_exists), así que
correrlo 2 veces no cambia nada. Los datos son deterministas (misma semilla, misma fecha base).

El esquema de claves está en KEY_SCHEMA (abajo) y documentado en contracts/dynamodb.md.
Si B cambia las claves en infra/base, se cambia SOLO ese diccionario.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seed_data  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = REPO_ROOT / "contracts" / "fixtures" / "seed"
DEFAULT_REGION = "us-east-1"

# --------------------------------------------------------------------------- contrato de claves
# dataset -> tabla (sufijo), atributo y valor de PK/SK, y GSIs (solo para --bootstrap-tables).
# Los GSIs usan atributos de dominio (zone, machine_id...) para que nadie tenga que mantener claves sintéticas.
KeyFn = Callable[[dict], str]
KEY_SCHEMA: dict[str, dict[str, Any]] = {
    "machines": {
        "table": "machines",
        "pk": ("pk", lambda i: f"{i['operation_id']}#{i['machine_id']}"),  # contratos.md §9 (A): OP-01#EX-023
        "sk": ("sk", lambda i: "META"),
        "gsis": [("by_zone", "zone", "machine_id")],
    },
    "technicians": {
        "table": "technicians",
        "pk": ("pk", lambda i: f"TECH#{i['technician_id']}"),
        "sk": ("sk", lambda i: "META"),
        "gsis": [("by_zone", "zone", "technician_id")],
    },
    "catalog": {
        "table": "catalog",
        "pk": ("pk", lambda i: f"COMPONENT#{i['component_id']}"),
        "sk": ("sk", lambda i: "META"),
        "gsis": [],
    },
    "machine_models": {  # misma tabla Catalog, otra entidad
        "table": "catalog",
        "pk": ("pk", lambda i: f"MODEL#{i['model_id']}"),
        "sk": ("sk", lambda i: "META"),
        "gsis": [],
    },
    "inventory": {
        "table": "inventory",
        "pk": ("pk", lambda i: i["location_id"]),  # contratos.md §9 (A): pk = WH-01
        "sk": ("sk", lambda i: i["component_id"]),  # sk = CMP-014
        "gsis": [("by_component", "component_id", "warehouse_id")],
    },
    "warehouses": {  # contratos.md §9: la SFN (B) y la analítica (A) leen coordenadas y zona del almacén
        "table": "warehouses",
        "pk": ("pk", lambda i: i["warehouse_id"]),  # pk = WH-01
        "sk": ("sk", lambda i: "META"),
        "gsis": [],
    },
    "notification_rules": {
        "table": "notification-rules",
        "pk": ("pk", lambda i: f"EVENT#{i['event_type']}"),
        "sk": ("sk", lambda i: f"ROLE#{i['role']}"),
        "gsis": [],
    },
}
# datasets que solo se exportan como fixture (no van a DynamoDB). Desde seed v2 `warehouses` sí se carga.
EXPORT_ONLY: set[str] = set()

# IDs que aparecen en contratos.md / openapi.yaml y DEBEN existir
CONTRACT_IDS = {
    "machines": ("machine_id", ["EX-023"]),
    "technicians": ("technician_id", ["TEC-07"]),
    "catalog": ("component_id", ["CMP-014"]),
    "inventory": ("warehouse_id", ["WH-01"]),
    "warehouses": ("warehouse_id", ["WH-01", "WH-04"]),
}


def table_name(stage: str, dataset: str) -> str:
    return f"arquifusion-{stage}-{KEY_SCHEMA[dataset]['table']}"


def to_item(dataset: str, record: dict) -> dict:
    """Agrega pk/sk al registro de dominio y convierte floats a Decimal (requisito de boto3).

    Omite los campos con valor None: DynamoDB guardaría un atributo de tipo NULL, y para
    attribute_exists / attribute_not_exists un NULL cuenta como existente. Eso rompería
    heartbeat (A, `attribute_exists(last_seen_at)`) y el dedup de procesar (A,
    `attribute_not_exists(open_incident_id)`). En los fixtures JSON el null se mantiene.
    """
    schema = KEY_SCHEMA[dataset]
    pk_attr, pk_fn = schema["pk"]
    sk_attr, sk_fn = schema["sk"]
    fields = {k: v for k, v in record.items() if v is not None}
    item = {pk_attr: pk_fn(record), sk_attr: sk_fn(record), "entity": dataset, **fields}
    return json.loads(json.dumps(item), parse_float=Decimal)


# --------------------------------------------------------------------------- export
def cmd_export(_args: argparse.Namespace) -> int:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    datasets = seed_data.build_all()
    for name, records in datasets.items():
        path = FIXTURES_DIR / f"{name}.json"
        path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  {path.relative_to(REPO_ROOT)}  ({len(records)} registros)")
    manifest = {
        "seed_version": seed_data.SEED_VERSION,
        "reference_date": seed_data.REFERENCE_DATE.isoformat(),
        "counts": {k: len(v) for k, v in datasets.items()},
        "machine_id_prefixes": {p["type"]: p["prefix"] for p in seed_data.FLEET_PLAN},
        "zones": list(seed_data.ZONES),
    }
    (FIXTURES_DIR / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("Export OK")
    return 0


# --------------------------------------------------------------------------- load
def _dynamodb(args: argparse.Namespace):
    try:
        import boto3
    except ImportError:
        sys.exit("Falta boto3: pip install -r scripts/requirements.txt")
    kwargs = {"region_name": args.region}
    if args.endpoint_url:
        kwargs["endpoint_url"] = args.endpoint_url
    return boto3.client("dynamodb", **kwargs), boto3.resource("dynamodb", **kwargs)


def put_records(table, dataset: str, records: list[dict], force: bool) -> tuple[int, int]:
    """Escribe con condición attribute_not_exists(pk). Devuelve (creados, omitidos). Testeable con un fake."""
    pk_attr = KEY_SCHEMA[dataset]["pk"][0]
    created = skipped = 0
    for record in records:
        item = to_item(dataset, record)
        kwargs: dict[str, Any] = {"Item": item}
        if not force:
            kwargs["ConditionExpression"] = "attribute_not_exists(#pk)"
            kwargs["ExpressionAttributeNames"] = {"#pk": pk_attr}
        try:
            table.put_item(**kwargs)
            created += 1
        except Exception as exc:  # ConditionalCheckFailedException -> ya existía
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code == "ConditionalCheckFailedException":
                skipped += 1
                continue
            raise
    return created, skipped


def bootstrap_tables(client, stage: str) -> None:
    """Crea tablas TEMPORALES para probar en tu lab personal antes de que exista infra/base de B.
    Bórralas antes de aplicar infra/base en esa cuenta (aws dynamodb delete-table ...)."""
    existing = set(client.list_tables()["TableNames"])
    tables: dict[str, list] = {}
    for dataset, schema in KEY_SCHEMA.items():
        tables.setdefault(table_name(stage, dataset), []).extend(schema["gsis"])
    for name, gsis in tables.items():
        if name in existing:
            print(f"  {name}: ya existe")
            continue
        attrs = {"pk", "sk"} | {g[1] for g in gsis} | {g[2] for g in gsis}
        params: dict[str, Any] = {
            "TableName": name,
            "BillingMode": "PAY_PER_REQUEST",
            "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            "AttributeDefinitions": [{"AttributeName": a, "AttributeType": "S"} for a in sorted(attrs)],
            "StreamSpecification": {"StreamEnabled": True, "StreamViewType": "NEW_AND_OLD_IMAGES"},
            "Tags": [
                {"Key": "project", "Value": "arquifusion"},
                {"Key": "owner", "Value": "C"},
                {"Key": "temporary", "Value": "bootstrap"},
            ],
        }
        if gsis:
            params["GlobalSecondaryIndexes"] = [
                {
                    "IndexName": idx,
                    "KeySchema": [{"AttributeName": h, "KeyType": "HASH"}, {"AttributeName": r, "KeyType": "RANGE"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
                for idx, h, r in gsis
            ]
        client.create_table(**params)
        print(f"  {name}: creando...")
        client.get_waiter("table_exists").wait(TableName=name)
        print(f"  {name}: ACTIVE")


def cmd_load(args: argparse.Namespace) -> int:
    if args.bootstrap_tables and args.stage == "dev":
        sys.exit(
            "--bootstrap-tables está prohibido en stage=dev: ahí las tablas las crea infra/base (B) con Terraform."
        )
    client, resource = _dynamodb(args)
    if args.bootstrap_tables:
        print("Bootstrap de tablas temporales:")
        bootstrap_tables(client, args.stage)
    existing = set(client.list_tables()["TableNames"])
    datasets = seed_data.build_all()
    missing = sorted({table_name(args.stage, d) for d in KEY_SCHEMA} - existing)
    if missing:
        sys.exit(f"Faltan tablas en la cuenta: {missing}. ¿B ya aplicó infra/base con stage={args.stage}?")
    total_c = total_s = 0
    for dataset in KEY_SCHEMA:
        name = table_name(args.stage, dataset)
        created, skipped = put_records(resource.Table(name), dataset, datasets[dataset], args.force)
        total_c += created
        total_s += skipped
        print(f"  {dataset:<20} -> {name:<40} creados={created:<4} ya_existían={skipped}")
    print(f"Load OK: {total_c} creados, {total_s} omitidos (force={args.force})")
    return 0


# --------------------------------------------------------------------------- verify
def cmd_verify(args: argparse.Namespace) -> int:
    client, resource = _dynamodb(args)
    expected = {k: len(v) for k, v in seed_data.build_all().items() if k not in EXPORT_ONLY}
    ok = True
    for dataset, _schema in KEY_SCHEMA.items():
        name = table_name(args.stage, dataset)
        count = 0
        scan_kwargs: dict[str, Any] = {
            "TableName": name,
            "Select": "COUNT",
            "FilterExpression": "#e = :e",
            "ExpressionAttributeNames": {"#e": "entity"},
            "ExpressionAttributeValues": {":e": {"S": dataset}},
        }
        while True:
            page = client.scan(**scan_kwargs)
            count += page["Count"]
            if "LastEvaluatedKey" not in page:
                break
            scan_kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        status = "OK " if count >= expected[dataset] else "FALTA"
        ok &= count >= expected[dataset]
        print(f"  [{status}] {dataset:<20} {count}/{expected[dataset]}  ({name})")
    for dataset, (field, ids) in CONTRACT_IDS.items():
        for _id in ids:
            record = next(r for r in seed_data.build_all()[dataset] if r[field] == _id)
            item = to_item(dataset, record)
            schema = KEY_SCHEMA[dataset]
            key = {schema["pk"][0]: item[schema["pk"][0]], schema["sk"][0]: item[schema["sk"][0]]}
            found = "Item" in resource.Table(table_name(args.stage, dataset)).get_item(Key=key)
            ok &= found
            print(f"  [{'OK ' if found else 'FALTA'}] contrato {_id} en {dataset}")
    print("Verify OK" if ok else "Verify con errores")
    return 0 if ok else 1


# --------------------------------------------------------------------------- reset-baselines
def delete_baselines(table) -> int:
    """Borra los ítems `sk = BASELINE` (propios y de cohorte) de `machine-state`. Devuelve cuántos borró.

    Necesario al pasar a un seed que cambia el modelo o la zona de máquinas existentes (v3 -> v4: 60 cambian de
    modelo): el EWMA propio aprendido con el `nominal` del modelo anterior generaría z-scores falsos. `procesar`
    los vuelve a aprender solo (warm-up). `LAST` y los agregados horarios se conservan.
    """
    deleted = 0
    scan_kwargs: dict[str, Any] = {
        "FilterExpression": "#sk = :b",
        "ProjectionExpression": "#pk, #sk",
        "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
        "ExpressionAttributeValues": {":b": "BASELINE"},
    }
    with table.batch_writer() as batch:
        while True:
            page = table.scan(**scan_kwargs)
            for item in page.get("Items", []):
                batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
                deleted += 1
            if "LastEvaluatedKey" not in page:
                break
            scan_kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    return deleted


def cmd_reset_baselines(args: argparse.Namespace) -> int:
    _client, resource = _dynamodb(args)
    name = f"arquifusion-{args.stage}-machine-state"
    print(f"Reset baselines: {delete_baselines(resource.Table(name))} ítems BASELINE borrados de {name}")
    return 0


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seeds de ArquiFusion (Persona C)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("export", help="Genera contracts/fixtures/seed/*.json")
    for name in ("load", "verify", "reset-baselines"):
        p = sub.add_parser(name)
        p.add_argument("--stage", required=True, help="dev (integración) o tu inicial (lab personal)")
        p.add_argument("--region", default=DEFAULT_REGION)
        p.add_argument("--endpoint-url", default=None, help="Ej. http://localhost:8000 para DynamoDB Local")
        if name == "load":
            p.add_argument("--force", action="store_true", help="Sobrescribe ítems existentes")
            p.add_argument("--bootstrap-tables", action="store_true", help="Crea tablas temporales (nunca en dev)")
    args = parser.parse_args(argv)
    commands = {"export": cmd_export, "load": cmd_load, "verify": cmd_verify, "reset-baselines": cmd_reset_baselines}
    return commands[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
