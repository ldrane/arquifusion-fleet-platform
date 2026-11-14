"""Lógica de replicar: DynamoDB Streams -> Firestore (RF-05, RF-15.3, RF-16, MH-HA-03, MH-MC-02).

Tablas -> colecciones (contratos.md §5):
- `{p}-machines`    -> `machines/{machine_id}`       mismo esquema que `MachineDetail` (sin `latest_reading`)
- `{p}-incidents`   -> `incidents/{incident_id}`     mismo esquema que `Incident`; SOLO ítems `sk = META` (#26)
- `{p}-technicians` -> `technicians/{technician_id}` `Technician` + `zone`; `location.zone` siempre presente (#11)

Reglas:
- Nunca se replican `pk`, `sk`, `entity`, `ack_token`, `resolve_token`, `execution_arn` (las proyecciones de
  `query_common.items` son listas blancas).
- `REMOVE` en DynamoDB -> `delete` del documento.
- Varios cambios del mismo documento en un lote -> solo se escribe el último (los Streams llegan ordenados por clave).
- Costo (Firestore cobra por escritura): `procesar` actualiza cada máquina en cada lectura (1/min). Un cambio de una
  máquina se replica de inmediato si cambia algo visible (`status`, `severity`, `open_incident_id`, salud ±5,
  mantenimiento, modelo…); si solo cambian campos "ruidosos" (`last_seen_at`, `operating_hours`, `location`,
  salud < 5 puntos) se replica como máximo una vez cada `REPLICA_HEARTBEAT_S` (300 s por defecto; 0 = siempre).
- Si Firestore falla, se lanza la excepción: el event source mapping reintenta con bisect y manda a la DLQ.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from query_common import gcp, items

HEALTH_DELTA = 5
NOISY_MACHINE_FIELDS = frozenset(
    {"last_seen_at", "operating_hours", "location", "health_score", "failure_probability", "rul_hours", "top_factors"}
)


def _deserializer():
    from boto3.dynamodb.types import TypeDeserializer

    return TypeDeserializer()


def _image(raw: dict | None) -> dict | None:
    if not raw:
        return None
    des = _deserializer()
    return {k: des.deserialize(v) for k, v in raw.items()}


def table_of(record: dict, env=os.environ) -> str | None:
    """Tipo de tabla a partir de `eventSourceARN` (`…:table/arquifusion-dev-machines/stream/…`)."""
    arn = record.get("eventSourceARN", "")
    name = arn.split(":table/", 1)[-1].split("/stream", 1)[0]
    for kind in ("machines", "incidents", "technicians"):
        if name == env.get(f"TABLE_{kind.upper()}") or name.endswith(f"-{kind}"):
            return kind
    return None


def _ts(value: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def machine_doc(item: dict) -> dict:
    doc = items.machine(item, detail=True)
    doc.pop(
        "latest_reading", None
    )  # la lectura completa se pide por REST (GET /machines/{id}); no se paga en cada write
    return doc


def machine_needs_write(new: dict, old: dict | None, heartbeat_s: int) -> bool:
    """¿Vale la pena escribir este cambio de máquina en Firestore? (ver docstring del módulo)."""
    if old is None or heartbeat_s <= 0:
        return True
    a, b = machine_doc(new), machine_doc(old)
    if any(a.get(k) != b.get(k) for k in a if k not in NOISY_MACHINE_FIELDS):
        return True
    if abs((a.get("health_score") or 0) - (b.get("health_score") or 0)) >= HEALTH_DELTA:
        return True
    if (a.get("location") or {}).get("zone") != (b.get("location") or {}).get("zone"):
        return True
    new_ts, old_ts = _ts(a.get("last_seen_at")), _ts(b.get("last_seen_at"))
    if new_ts is None or old_ts is None:
        return a != b
    return int(new_ts // heartbeat_s) != int(old_ts // heartbeat_s)


def incident_doc(item: dict) -> dict:
    doc = items.incident(item)
    if item.get("correlation_id"):
        doc["correlation_id"] = item["correlation_id"]  # trazabilidad de punta a punta (contratos.md §1)
    return doc


def technician_doc(item: dict) -> dict:
    doc = items.technician(item)
    zone = item.get("zone") or (doc.get("location") or {}).get("zone")
    doc["zone"] = zone  # respaldo de las Security Rules si algún escritor omite location.zone
    return doc


def plan(records: list[dict], heartbeat_s: int, env=os.environ) -> tuple[dict[str, dict | None], dict[str, int]]:
    """Convierte los registros del Stream en `{ruta_documento: doc | None(=borrar)}` (el último gana)."""
    ops: dict[str, dict | None] = {}
    stats = {"records": len(records), "ignored": 0, "throttled": 0}
    for rec in records:
        kind = table_of(rec, env)
        ddb = rec.get("dynamodb") or {}
        keys = _image(ddb.get("Keys")) or {}
        new, old = _image(ddb.get("NewImage")), _image(ddb.get("OldImage"))
        current = new or old or {}
        if kind is None or keys.get("sk", current.get("sk")) != "META":
            stats["ignored"] += 1  # EVT# de incidentes (#26) u otra tabla
            continue
        if kind == "machines":
            doc_id, build = current.get("machine_id"), machine_doc
        elif kind == "incidents":
            doc_id, build = current.get("incident_id"), incident_doc
        else:
            doc_id, build = current.get("technician_id"), technician_doc
        if not doc_id:
            stats["ignored"] += 1
            continue
        path = f"{kind}/{doc_id}"
        if rec.get("eventName") == "REMOVE" or new is None:
            ops[path] = None
            continue
        if kind == "machines" and path not in ops and not machine_needs_write(new, old, heartbeat_s):
            stats["throttled"] += 1
            continue
        ops[path] = build(new)
    return ops, stats


_firestore: gcp.Firestore | None = None


def default_firestore(env=os.environ) -> gcp.Firestore:
    global _firestore
    if _firestore is None:
        import boto3

        secret = env.get("FIREBASE_SECRET_NAME") or f"arquifusion/{env.get('STAGE', 'dev')}/gcp/service-account"
        sa = gcp.load_service_account(secret, boto3.client("secretsmanager"))
        _firestore = gcp.firestore_from_service_account(sa, env.get("GCP_PROJECT_ID") or None)
    return _firestore


def run(event: dict, firestore: gcp.Firestore | None = None, env=os.environ) -> dict:
    heartbeat_s = int(env.get("REPLICA_HEARTBEAT_S", "300"))
    ops, stats = plan(event.get("Records") or [], heartbeat_s, env)
    if ops:
        fs = firestore or default_firestore(env)
        writes = [fs.delete_write(p) if doc is None else fs.set_write(p, doc) for p, doc in ops.items()]
        stats["written"] = fs.commit(writes)
    else:
        stats["written"] = 0
    stats["at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return stats
