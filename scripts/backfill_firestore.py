"""Carga inicial de Firestore desde DynamoDB (RF-05, RF-15.3, MH-HA-03).

`replicar` solo reacciona a DynamoDB Streams: lo que se escribió antes de tener la llave de GCP en Secrets Manager
(seeds, incidentes del smoke) nunca llega a Firestore. Este script lee machines / incidents / technicians y le pasa
a la Lambda `replicar` eventos INSERT sintéticos con la misma forma que un stream. No modifica DynamoDB.

Uso: python scripts/backfill_firestore.py --stage dev [--region us-east-1] [--batch 100]
"""

import argparse
import json

import boto3

TABLES = ("machines", "incidents", "technicians")


def records_for(table: str, items: list[dict], region: str, account: str) -> list[dict]:
    arn = f"arn:aws:dynamodb:{region}:{account}:table/{table}/stream/backfill"
    return [{"eventName": "INSERT", "eventSourceARN": arn, "dynamodb": {"NewImage": it}} for it in items]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stage", required=True)
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--batch", type=int, default=100)
    args = ap.parse_args()

    prefix = f"arquifusion-{args.stage}"
    account = boto3.client("sts", region_name=args.region).get_caller_identity()["Account"]
    ddb = boto3.client("dynamodb", region_name=args.region)
    lam = boto3.client("lambda", region_name=args.region)

    for short in TABLES:
        table = f"{prefix}-{short}"
        items = [it for page in ddb.get_paginator("scan").paginate(TableName=table) for it in page["Items"]]
        sent = 0
        for i in range(0, len(items), args.batch):
            event = {"Records": records_for(table, items[i : i + args.batch], args.region, account)}
            resp = lam.invoke(FunctionName=f"{prefix}-replicar", Payload=json.dumps(event).encode())
            body = resp["Payload"].read().decode()
            if resp.get("FunctionError"):
                raise SystemExit(f"{table}: replicar falló: {body[:500]}")
            sent += len(event["Records"])
        print(f"  {short:<12} {sent:>4} ítems -> replicar  (última respuesta: {body[:160]})")
    print("Backfill OK")


if __name__ == "__main__":
    main()
