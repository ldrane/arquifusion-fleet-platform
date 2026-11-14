"""Detección de máquinas silenciosas (OBS-09, RF-05).

Cada 1 min (EventBridge Scheduler; antes 5 min) recorre `machines` y marca `status = silent` las máquinas cuya última lectura
(`last_seen_at`) es más antigua que `factor × expected_interval_s` (por defecto 3 × 60 s). Por cada máquina que pasa a
silenciosa emite UN `MachineSilent` (contratos.md §3) con `zone` (del seed) y `silence_threshold_s` = factor ×
`expected_interval_s` (#21). La escritura es condicional sobre `last_seen_at`, así que:
- no se emite dos veces por el mismo silencio;
- si llega una lectura nueva entre el scan y la escritura, no se marca.
Cuando `procesar` recibe una lectura nueva, el status deja de ser `silent` y un silencio posterior vuelve a emitir.

Nota de escala: el scan es suficiente para cientos de máquinas. Para miles conviene un GSI por `status`/`last_seen_at`.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from botocore.exceptions import ClientError

EVENT_SOURCE = "arquifusion.heartbeat"
EVENT_TYPE = "MachineSilent"
SILENT = "silent"


@dataclass(frozen=True)
class HeartbeatConfig:
    default_interval_s: int = 60
    silence_factor: int = 3


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _is_conditional_failure(exc: ClientError) -> bool:
    return exc.response["Error"]["Code"] == "ConditionalCheckFailedException"


class Heartbeat:
    def __init__(
        self,
        machines_table,
        publish: Callable[[dict], None],
        config: HeartbeatConfig,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        """`machines_table` es una `Table` de boto3; `publish(detail)` envía el evento a EventBridge."""
        self._table = machines_table
        self._publish = publish
        self._config = config
        self._clock = clock

    def run(self) -> dict:
        now = self._clock()
        candidates = silenced = 0
        for machine in self._scan_active():
            interval = int(machine.get("expected_interval_s") or self._config.default_interval_s)
            threshold = interval * self._config.silence_factor
            if now - _parse(machine["last_seen_at"]) <= timedelta(seconds=threshold):
                continue
            candidates += 1
            if self._mark_silent(machine, now):
                self._emit(machine, interval, threshold, now)
                silenced += 1
        return {"candidates": candidates, "silenced": silenced}

    def _scan_active(self):
        """Máquinas con lectura previa que aún no están en silencio, paginando el scan."""
        kwargs = {
            "ProjectionExpression": "pk, sk, machine_id, #zone, last_seen_at, expected_interval_s, #st",
            "FilterExpression": (
                "sk = :meta AND attribute_exists(last_seen_at) AND (attribute_not_exists(#st) OR #st <> :silent)"
            ),
            "ExpressionAttributeNames": {"#st": "status", "#zone": "zone"},
            "ExpressionAttributeValues": {":meta": "META", ":silent": SILENT},
        }
        while True:
            page = self._table.scan(**kwargs)
            yield from page.get("Items", [])
            if "LastEvaluatedKey" not in page:
                return
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    def _mark_silent(self, machine: dict, now: datetime) -> bool:
        try:
            self._table.update_item(
                Key={"pk": machine["pk"], "sk": machine["sk"]},
                UpdateExpression="SET #st = :silent, status_before_silent = :prev, silent_since = :now",
                ConditionExpression="last_seen_at = :seen AND (attribute_not_exists(#st) OR #st <> :silent)",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={
                    ":silent": SILENT,
                    ":prev": machine.get("status", "operational"),
                    ":now": _iso(now),
                    ":seen": machine["last_seen_at"],
                },
            )
            return True
        except ClientError as exc:
            if _is_conditional_failure(exc):
                return False
            raise

    def _restore(self, machine: dict) -> None:
        """Deshace la marca si no se pudo emitir el evento: el próximo ciclo lo reintenta."""
        self._table.update_item(
            Key={"pk": machine["pk"], "sk": machine["sk"]},
            UpdateExpression="SET #st = :prev REMOVE silent_since, status_before_silent",
            ConditionExpression="#st = :silent",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={":prev": machine.get("status", "operational"), ":silent": SILENT},
        )

    def _emit(self, machine: dict, interval: int, threshold: int, now: datetime) -> None:
        detail = {
            "event_id": str(uuid.uuid4()),
            "correlation_id": str(uuid.uuid4()),
            "occurred_at": _iso(now),
            "version": 1,
            "data": {
                "machine_id": machine["machine_id"],
                "zone": machine.get("zone"),
                "last_seen_at": machine["last_seen_at"],
                "expected_interval_s": interval,
                "silence_threshold_s": threshold,
            },
        }
        try:
            self._publish(detail)
        except Exception:
            self._restore(machine)
            raise
