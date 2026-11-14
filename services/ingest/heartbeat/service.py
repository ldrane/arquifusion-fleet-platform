"""Detección de máquinas silenciosas (OBS-09, RF-05).

Cada 1 min (EventBridge Scheduler; antes 5 min) recorre `machines` y marca `status = silent` las máquinas cuya
última lectura (`last_seen_at`) es más antigua que `factor × expected_interval_s` (por defecto 3 × 60 s). Por cada
máquina que pasa a silenciosa emite UN `MachineSilent` (contratos.md §3) con `zone` (del seed) y
`silence_threshold_s` = factor × `expected_interval_s` (#21). La escritura es condicional sobre `last_seen_at`, así que:
- no se emite dos veces por el mismo silencio;
- si llega una lectura nueva entre el scan y la escritura, no se marca.
Cuando `procesar` recibe una lectura nueva, el status deja de ser `silent` y un silencio posterior vuelve a emitir.
Protección de tormenta: si >= 5 máquinas y >= 20 % de las activas se callan a la vez (caída de la ingesta, p. ej. se
detuvo el simulador) se marcan `silent` sin emitir eventos; fuera de tormenta se emiten como máximo 5 por corrida.

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
    # Protección de tormenta (RNF costo / límite de concurrencia de AWS Academy):
    max_events_per_run: int = 5  # MachineSilent máximos por corrida
    storm_min_machines: int = 5  # silencio simultáneo de >= N máquinas…
    storm_ratio: float = 0.2  # …y >= 20 % de las activas = caída de ingesta, no fallas individuales


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
        active = 0
        pending: list[tuple[dict, int, int]] = []
        for machine in self._scan_active():
            active += 1
            interval = int(machine.get("expected_interval_s") or self._config.default_interval_s)
            threshold = interval * self._config.silence_factor
            if now - _parse(machine["last_seen_at"]) > timedelta(seconds=threshold):
                pending.append((machine, interval, threshold))

        cfg = self._config
        # Tormenta = caída de la ingesta (p. ej. se detuvo el simulador), no N fallas de máquina: se marcan `silent`
        # para el mapa pero NO se abren incidentes (cada uno dispara ~5 Lambdas; AWS Academy limita a 10 en paralelo).
        storm = len(pending) >= cfg.storm_min_machines and len(pending) >= cfg.storm_ratio * active
        silenced = suppressed = 0
        for machine, interval, threshold in pending:
            if not storm and silenced >= cfg.max_events_per_run:
                break  # el resto se evalúa en el próximo ciclo (1 min): acota la ráfaga de GestionIncidente
            if not self._mark_silent(machine, now):
                continue
            if storm:
                suppressed += 1
                continue
            self._emit(machine, interval, threshold, now)
            silenced += 1
        return {
            "active": active,
            "candidates": len(pending),
            "silenced": silenced,
            "storm": storm,
            "storm_suppressed": suppressed,
        }

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
