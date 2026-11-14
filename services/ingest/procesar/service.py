"""Lógica de `procesar`: de un lote SQS de lecturas a estado, anomalías, lake y eventos (RF-02, RF-09, RNF-07).

Por cada mensaje SQS (un lote de hasta 100 lecturas de `POST /telemetry`):
1. Idempotencia por `machine_id#timestamp` (RNF-07).
2. Por máquina, en orden de timestamp: capa 1 reglas, capa 2 z-score (propio y de cohorte), capa 3 IsolationForest.
3. Combina las capas en health score, severidad y top-3 factores (explicabilidad).
4. Guarda baseline, última lectura y agregados por hora (`machine-state`), estado de la máquina (`machines`),
   anomalías con severidad ≥ media (`anomalies`) y la lectura cruda en el lake (Firehose).
5. Emite `AnomalyDetected` solo si la máquina no tiene incidente abierto ni bloqueo vigente (contratos.md §9).

Un mensaje que falla se devuelve en `batchItemFailures` y libera sus registros de idempotencia,
para que el reintento de SQS lo procese completo. Tras 3 intentos va a la DLQ.
"""

import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from arquifusion_ml.features import MONITORED
from arquifusion_ml.lake import flatten_reading
from arquifusion_shared.observability import logger, metrics
from aws_lambda_powertools.metrics import MetricUnit
from ingest_procesar import rules, scoring
from ingest_procesar.baseline import Baseline, zscores
from ingest_procesar.message import InvalidMessage, parse

EVENT_SOURCE = "arquifusion.processor"
EVENT_TYPE = "AnomalyDetected"
NO_MODEL = "baseline-only"


@dataclass
class Evaluated:
    """Resultado de evaluar una lectura."""

    reading: dict
    assessment: scoring.Assessment
    model_version: str


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _hour(timestamp: str) -> str:
    return timestamp[:13]  # YYYY-MM-DDTHH


def _cohort_pk(reading: dict) -> str:
    return f"COHORT#{reading['type']}#{reading['location'].get('zone', 'sin-zona')}"


def _agg_sk(timestamp: str) -> str:
    return f"AGG#1h#{_hour(timestamp)}"


class Processor:
    def __init__(
        self, settings, repo, thresholds: rules.ThresholdProvider, models, clock: Callable[[], datetime] = _utcnow
    ):
        self._s = settings
        self._repo = repo
        self._thresholds = thresholds
        self._models = models
        self._clock = clock

    # ------------------------------------------------------------------ entrada
    def handle(self, event: dict) -> dict:
        """Procesa el evento SQS y devuelve las fallas parciales (ReportBatchItemFailures)."""
        failures = []
        for record in event.get("Records", []):
            try:
                self.process_message(record["body"])
            except InvalidMessage:
                logger.exception("Mensaje SQS inválido", extra={"message_id": record.get("messageId")})
                failures.append({"itemIdentifier": record["messageId"]})
            except Exception:
                logger.exception("Error procesando mensaje", extra={"message_id": record.get("messageId")})
                failures.append({"itemIdentifier": record["messageId"]})
        return {"batchItemFailures": failures}

    def process_message(self, body: str) -> None:
        envelope = parse(body)
        logger.append_keys(correlation_id=envelope.correlation_id)
        if envelope.invalid:
            logger.warning("Lecturas incompletas descartadas", extra={"count": envelope.invalid})
            metrics.add_metric(name="ReadingsInvalid", unit=MetricUnit.Count, value=envelope.invalid)

        now = self._clock()
        readings = sorted(envelope.readings, key=lambda r: r["timestamp"])
        claimed = [
            r for r in readings if self._repo.claim_reading(r["machine_id"], r["timestamp"], int(now.timestamp()))
        ]
        duplicates = len(readings) - len(claimed)
        if duplicates:
            metrics.add_metric(name="ReadingsDuplicated", unit=MetricUnit.Count, value=duplicates)
        if not claimed:
            return

        try:
            self._process_readings(claimed, envelope.correlation_id, now)
        except Exception:
            for r in claimed:
                self._repo.release_reading(r["machine_id"], r["timestamp"])
            raise
        metrics.add_metric(name="ReadingsProcessed", unit=MetricUnit.Count, value=len(claimed))

    # ------------------------------------------------------------------ evaluación
    def _process_readings(self, readings: list[dict], correlation_id: str, now: datetime) -> None:
        state = self._repo.load_state(self._state_keys(readings))
        by_machine: dict[str, list[dict]] = defaultdict(list)
        for r in readings:
            by_machine[r["machine_id"]].append(r)

        dirty: dict[tuple[str, str], dict] = {}
        lake_rows, anomalies, to_emit, machine_updates = [], [], [], []
        for machine_readings in by_machine.values():
            evaluated = [self._evaluate(r, state, dirty) for r in machine_readings]
            last = evaluated[-1]
            machine_updates.append((self._machine_pk(last.reading), self._machine_fields(last)))
            alerts = [e for e in evaluated if scoring.is_alert(e.assessment.severity)]
            anomalies.extend(self._anomaly_item(e, correlation_id) for e in alerts)
            if alerts:
                # Se emite la lectura más grave del lote (la más reciente si empatan).
                to_emit.append(max(alerts, key=lambda e: scoring.SEVERITY_ORDER.index(e.assessment.severity)))
            lake_rows.extend(self._lake_row(e, correlation_id) for e in evaluated)

        self._repo.save_state(dirty.values())
        for pk, fields in machine_updates:
            self._repo.update_machine(pk, fields)
        self._repo.put_anomalies(anomalies)
        self._repo.send_to_lake(lake_rows)
        for e in to_emit:
            self._emit_anomaly(e, correlation_id, now)
        if anomalies:
            metrics.add_metric(name="AnomaliesDetected", unit=MetricUnit.Count, value=len(anomalies))

    def _state_keys(self, readings: list[dict]) -> list[tuple[str, str]]:
        keys = []
        for r in readings:
            keys += [
                (r["machine_id"], "BASELINE"),
                (r["machine_id"], "LAST"),
                (r["machine_id"], _agg_sk(r["timestamp"])),
                (_cohort_pk(r), "BASELINE"),
            ]
        return keys

    def _evaluate(self, reading: dict, state: dict, dirty: dict) -> Evaluated:
        """Aplica las 3 capas a una lectura y actualiza en memoria baseline, LAST y agregados."""
        machine_id = reading["machine_id"]
        values = {v: float(reading[v]) for v in MONITORED}

        own_key, cohort_key = (machine_id, "BASELINE"), (_cohort_pk(reading), "BASELINE")
        own = Baseline.from_item(state.get(own_key, {}).get("stats"))
        cohort = Baseline.from_item(state.get(cohort_key, {}).get("stats"))
        warmup = self._s.warmup_readings

        hits = rules.evaluate(reading, self._thresholds.get(reading["type"]))
        z_own, z_cohort = zscores(own, values, warmup), zscores(cohort, values, warmup)
        ml = self._score_ml(reading)
        assessment = scoring.assess(reading, hits, z_own, z_cohort, ml.risk if ml else None)

        # Las lecturas en alerta no alimentan el baseline: una falla no debe volverse "normal".
        if not scoring.is_alert(assessment.severity):
            own.update(values, self._s.ewma_alpha)
            cohort.update(values, self._s.ewma_alpha)
        for key, baseline in ((own_key, own), (cohort_key, cohort)):
            state[key] = dirty[key] = {"pk": key[0], "sk": key[1], "stats": baseline.to_item()}

        last_key = (machine_id, "LAST")
        state[last_key] = dirty[last_key] = {
            "pk": machine_id,
            "sk": "LAST",
            "reading": reading,
            "health_score": assessment.health_score,
            "severity": assessment.severity,
        }
        agg_key = (machine_id, _agg_sk(reading["timestamp"]))
        state[agg_key] = dirty[agg_key] = self._aggregate(state.get(agg_key), agg_key, values)
        return Evaluated(reading, assessment, ml.model_version if ml else NO_MODEL)

    def _score_ml(self, reading: dict):
        """Capa 3. Una falla del modelo nunca detiene el procesamiento: se sigue con las capas 1 y 2."""
        try:
            return self._models.score(reading)
        except Exception:
            logger.exception("Capa ML no disponible; se continúa con reglas y z-score")
            return None

    @staticmethod
    def _aggregate(item: dict | None, key: tuple[str, str], values: dict[str, float]) -> dict:
        """Agregado horario por variable: min, max, sum y avg (schema Aggregate del OpenAPI)."""
        item = item or {"pk": key[0], "sk": key[1], "count": 0, "vars": {}}
        item["count"] += 1
        for v, x in values.items():
            agg = item["vars"].setdefault(v, {"min": x, "max": x, "sum": 0.0})
            agg["min"], agg["max"] = min(agg["min"], x), max(agg["max"], x)
            agg["sum"] += x
            agg["avg"] = agg["sum"] / item["count"]
        return item

    # ------------------------------------------------------------------ salidas
    def _machine_pk(self, reading: dict) -> str:
        return f"{self._s.default_operation_id}#{reading['machine_id']}"

    def _machine_fields(self, e: Evaluated) -> dict:
        r, a = e.reading, e.assessment
        return {
            "machine_id": r["machine_id"],
            "operation_id": self._s.default_operation_id,
            "type": r["type"],
            "model": r.get("model"),
            "zone": r["location"].get("zone"),
            "location": r["location"],
            "status": a.status,
            "severity": a.severity,
            "health_score": a.health_score,
            "failure_probability": a.risk,
            "top_factors": a.top_factors,
            "model_version": e.model_version,
            "operating_hours": r.get("operating_hours"),
            "latest_reading": r,
            "last_seen_at": r["timestamp"],
        }

    def _anomaly_item(self, e: Evaluated, correlation_id: str) -> dict:
        r, a = e.reading, e.assessment
        zone = r["location"].get("zone", "sin-zona")
        return {
            "pk": r["machine_id"],
            "sk": f"{r['timestamp']}#{uuid.uuid4().hex[:12]}",
            "gsi1pk": f"{zone}#{r['timestamp'][:10]}",
            "gsi1sk": r["timestamp"],
            "machine_id": r["machine_id"],
            "zone": zone,
            "machine_type": r["type"],
            "severity": a.severity,
            "anomaly_score": a.risk,
            "health_score": a.health_score,
            "top_factors": a.top_factors,
            "kind": "individual",
            "model_version": e.model_version,
            "correlation_id": correlation_id,
        }

    def _lake_row(self, e: Evaluated, correlation_id: str) -> dict:
        r = e.reading
        row = flatten_reading(r)
        row.update(
            health_score=e.assessment.health_score,
            severity=e.assessment.severity,
            correlation_id=correlation_id,
            # Claves de partición que extrae el dynamic partitioning de Firehose.
            operation_id=self._s.default_operation_id,
            dt=r["timestamp"][:10],
            machine_type=r["type"],
        )
        return row

    def _emit_anomaly(self, e: Evaluated, correlation_id: str, now: datetime) -> None:
        r, a = e.reading, e.assessment
        pk = self._machine_pk(r)
        until = _iso(now + timedelta(seconds=self._s.anomaly_lock_s))
        if not self._repo.claim_anomaly_lock(pk, _iso(now), until):
            logger.info(
                "AnomalyDetected omitido: incidente abierto o bloqueo vigente", extra={"machine_id": r["machine_id"]}
            )
            return
        detail = {
            "event_id": str(uuid.uuid4()),
            "correlation_id": correlation_id,
            "occurred_at": _iso(now),
            "version": 1,
            "data": {
                "machine_id": r["machine_id"],
                "zone": r["location"].get("zone"),
                "severity": a.severity,
                "anomaly_score": a.risk,
                "top_factors": a.top_factors,
                "health_score": a.health_score,
                "model_version": e.model_version,
                "reading_ts": r["timestamp"],
            },
        }
        try:
            self._repo.publish_event(EVENT_SOURCE, EVENT_TYPE, detail)
        except Exception:
            self._repo.release_anomaly_lock(pk, until)
            raise
        logger.info("AnomalyDetected emitido", extra={"machine_id": r["machine_id"], "severity": a.severity})
        metrics.add_metric(name="AnomalyEventsEmitted", unit=MetricUnit.Count, value=1)
