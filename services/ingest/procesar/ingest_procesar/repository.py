"""Acceso a datos de `procesar`: DynamoDB, Firehose y EventBridge (RF-01.4, RF-02, RNF-07).

Keyschema esperado de las tablas de infra/base (Persona B). Atributos `pk` y `sk` de tipo string:

- machines:      pk `{operation_id}#{machine_id}`, sk `META`.
- machine-state: pk `{machine_id}` o `COHORT#{type}#{zone}`; sk `LAST`, `BASELINE` o `AGG#1h#{YYYY-MM-DDTHH}`.
- idempotency:   pk `{machine_id}#{timestamp}`, sin sk, TTL en `expires_at`.
- anomalies:     pk `{machine_id}`, sk `{timestamp}#{anomaly_id}`;
                 GSI1 `gsi1pk` = `{zone}#{YYYY-MM-DD}`, `gsi1sk` = timestamp.
"""

import json
from collections.abc import Iterable
from decimal import Decimal

from botocore.exceptions import ClientError

CONDITIONAL_FAILED = "ConditionalCheckFailedException"
FIREHOSE_MAX_BATCH = 500
DDB_MAX_BATCH_GET = 100


def to_dynamo(value):
    """Convierte floats a Decimal (DynamoDB no acepta float)."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: to_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_dynamo(v) for v in value]
    return value


def from_dynamo(value):
    """Convierte Decimal a float/int para trabajar en memoria."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: from_dynamo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_dynamo(v) for v in value]
    return value


def _is_conditional_failure(exc: ClientError) -> bool:
    return exc.response["Error"]["Code"] == CONDITIONAL_FAILED


class Repository:
    def __init__(self, settings, dynamodb, firehose, events):
        """`dynamodb` es un `boto3.resource('dynamodb')`; `firehose` y `events` son clientes boto3."""
        self._s = settings
        self._ddb = dynamodb
        self._machines = dynamodb.Table(settings.table_machines)
        self._state = dynamodb.Table(settings.table_machine_state)
        self._idempotency = dynamodb.Table(settings.table_idempotency)
        self._anomalies = dynamodb.Table(settings.table_anomalies)
        self._firehose = firehose
        self._events = events

    # ------------------------------------------------------------------ idempotencia (RNF-07)
    def claim_reading(self, machine_id: str, timestamp: str, now_epoch: int) -> bool:
        """Registra la lectura. False si ya se había procesado (duplicado)."""
        try:
            self._idempotency.put_item(
                Item={"pk": f"{machine_id}#{timestamp}", "expires_at": now_epoch + self._s.idempotency_ttl_s},
                ConditionExpression="attribute_not_exists(pk)",
            )
            return True
        except ClientError as exc:
            if _is_conditional_failure(exc):
                return False
            raise

    def release_reading(self, machine_id: str, timestamp: str) -> None:
        """Libera el registro si el mensaje falla, para que el reintento de SQS la procese."""
        self._idempotency.delete_item(Key={"pk": f"{machine_id}#{timestamp}"})

    # ------------------------------------------------------------------ estado (ESC-07)
    def load_state(self, keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], dict]:
        """Lee ítems de machine-state por (pk, sk) con BatchGetItem."""
        pending = [{"pk": pk, "sk": sk} for pk, sk in dict.fromkeys(keys)]
        found: dict[tuple[str, str], dict] = {}
        for start in range(0, len(pending), DDB_MAX_BATCH_GET):
            request = {self._s.table_machine_state: {"Keys": pending[start : start + DDB_MAX_BATCH_GET]}}
            while request:
                response = self._ddb.batch_get_item(RequestItems=request)
                for item in response["Responses"].get(self._s.table_machine_state, []):
                    found[(item["pk"], item["sk"])] = from_dynamo(item)
                request = response.get("UnprocessedKeys") or None
        return found

    def save_state(self, items: Iterable[dict]) -> None:
        with self._state.batch_writer(overwrite_by_pkeys=["pk", "sk"]) as batch:
            for item in items:
                batch.put_item(Item=to_dynamo(item))

    # ------------------------------------------------------------------ máquina (RF-05)
    def update_machine(self, pk: str, fields: dict) -> bool:
        """Actualiza el estado de la máquina. Ignora lecturas más antiguas que la última guardada."""
        names = {f"#{k}": k for k in fields}
        values = {f":{k}": to_dynamo(v) for k, v in fields.items()}
        try:
            self._machines.update_item(
                Key={"pk": pk, "sk": "META"},
                UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
                ConditionExpression="attribute_not_exists(#last_seen_at) OR #last_seen_at <= :last_seen_at",
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
            )
            return True
        except ClientError as exc:
            if _is_conditional_failure(exc):
                return False
            raise

    def claim_anomaly_lock(self, pk: str, now_iso: str, until_iso: str) -> bool:
        """Dedup de AnomalyDetected (contratos.md §9): solo pasa si no hay incidente abierto ni bloqueo vigente."""
        try:
            self._machines.update_item(
                Key={"pk": pk, "sk": "META"},
                UpdateExpression="SET anomaly_lock_until = :until",
                ConditionExpression=(
                    "attribute_not_exists(open_incident_id) AND "
                    "(attribute_not_exists(anomaly_lock_until) OR anomaly_lock_until < :now)"
                ),
                ExpressionAttributeValues={":until": until_iso, ":now": now_iso},
            )
            return True
        except ClientError as exc:
            if _is_conditional_failure(exc):
                return False
            raise

    def release_anomaly_lock(self, pk: str, until_iso: str) -> None:
        """Quita el bloqueo propio si no se pudo publicar el evento, para que el reintento lo emita."""
        try:
            self._machines.update_item(
                Key={"pk": pk, "sk": "META"},
                UpdateExpression="REMOVE anomaly_lock_until",
                ConditionExpression="anomaly_lock_until = :until",
                ExpressionAttributeValues={":until": until_iso},
            )
        except ClientError as exc:
            if not _is_conditional_failure(exc):
                raise

    # ------------------------------------------------------------------ anomalías (RF-09)
    def put_anomalies(self, items: Iterable[dict]) -> None:
        with self._anomalies.batch_writer() as batch:
            for item in items:
                batch.put_item(Item=to_dynamo(item))

    # ------------------------------------------------------------------ lake (RF-01.4)
    def send_to_lake(self, rows: list[dict]) -> None:
        """Envía filas a Firehose. Reintenta una vez las fallidas; si siguen fallando, lanza error."""
        for start in range(0, len(rows), FIREHOSE_MAX_BATCH):
            records = [
                {"Data": (json.dumps(r, default=str) + "\n").encode()} for r in rows[start : start + FIREHOSE_MAX_BATCH]
            ]
            for _attempt in range(2):
                response = self._firehose.put_record_batch(DeliveryStreamName=self._s.firehose_stream, Records=records)
                if not response.get("FailedPutCount"):
                    break
                records = [
                    rec for rec, res in zip(records, response["RequestResponses"], strict=True) if "ErrorCode" in res
                ]
            else:
                raise RuntimeError(f"Firehose rechazó {len(records)} registros")

    # ------------------------------------------------------------------ eventos (contratos.md §3)
    def publish_event(self, source: str, detail_type: str, detail: dict) -> None:
        response = self._events.put_events(
            Entries=[
                {
                    "Source": source,
                    "DetailType": detail_type,
                    "EventBusName": self._s.event_bus_name,
                    "Detail": json.dumps(detail, default=str),
                }
            ]
        )
        if response.get("FailedEntryCount"):
            raise RuntimeError(f"EventBridge rechazó {detail_type}: {response['Entries']}")
