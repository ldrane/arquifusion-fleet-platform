"""Configuración de `procesar` leída de variables de entorno (las define infra/ingest/procesar.tf)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    stage: str
    table_machines: str
    table_machine_state: str
    table_idempotency: str
    table_anomalies: str
    event_bus_name: str
    firehose_stream: str
    model_bucket: str
    default_operation_id: str = "OP-01"
    ewma_alpha: float = 0.05  # peso de la lectura nueva en el baseline EWMA
    warmup_readings: int = 20  # lecturas mínimas antes de confiar en el z-score
    idempotency_ttl_s: int = 24 * 3600  # RNF-07: ventana de deduplicación
    # Reclamo `pending` (F-18): > timeout de la Lambda (55 s) y < visibilidad de la cola (60 s), para que el
    # reintento de SQS tras un timeout/OOM encuentre el reclamo vencido y reprocese la lectura.
    claim_pending_s: int = 56
    anomaly_lock_s: int = 600  # contratos.md §9: bloqueo de reemisión de AnomalyDetected
    cache_ttl_s: int = 300  # caché de SSM (umbrales y versión del modelo)

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        return cls(
            stage=env["STAGE"],
            table_machines=env["TABLE_MACHINES"],
            table_machine_state=env["TABLE_MACHINE_STATE"],
            table_idempotency=env["TABLE_IDEMPOTENCY"],
            table_anomalies=env["TABLE_ANOMALIES"],
            event_bus_name=env["EVENT_BUS_NAME"],
            firehose_stream=env["FIREHOSE_STREAM"],
            model_bucket=env["MODEL_BUCKET"],
            default_operation_id=env.get("DEFAULT_OPERATION_ID", "OP-01"),
            ewma_alpha=float(env.get("EWMA_ALPHA", "0.05")),
            warmup_readings=int(env.get("WARMUP_READINGS", "20")),
        )
