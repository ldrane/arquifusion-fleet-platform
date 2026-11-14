"""Envío de telemetría a `POST /telemetry` (RF-01.1, RF-01.3).

Lotes de hasta 100 lecturas, header `x-api-key`, `X-Correlation-Id` por lote y reintentos con
backoff exponencial ante 429, 5xx o errores de red.
"""

import random
import time
import uuid
from collections.abc import Callable, Iterable, Iterator

import requests

MAX_BATCH = 100
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class SendError(RuntimeError):
    """El lote no se pudo entregar (error no reintentable o reintentos agotados)."""


def batches(readings: Iterable[dict], size: int = MAX_BATCH) -> Iterator[list[dict]]:
    """Agrupa lecturas en lotes de como máximo `size` (el contrato admite 1-100)."""
    if not 1 <= size <= MAX_BATCH:
        raise ValueError(f"size debe estar entre 1 y {MAX_BATCH}")
    batch: list[dict] = []
    for r in readings:
        batch.append(r)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


class TelemetrySender:
    """Cliente HTTP de la API de ingesta."""

    def __init__(
        self,
        api_url: str,
        api_key: str,
        *,
        session: requests.Session | None = None,
        max_retries: int = 5,
        backoff_base_s: float = 0.5,
        timeout_s: float = 10.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not api_url or not api_key:
            raise ValueError("Faltan api_url o api_key (usa SIMULATOR_API_URL / SIMULATOR_API_KEY)")
        self.url = api_url.rstrip("/") + "/telemetry"
        self.api_key = api_key
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.timeout_s = timeout_s
        self.sleep = sleep

    def send(self, readings: Iterable[dict]) -> list[str]:
        """Envía todas las lecturas y devuelve el correlation_id de cada lote."""
        return [self.send_batch(b) for b in batches(readings)]

    def send_batch(self, batch: list[dict]) -> str:
        correlation_id = str(uuid.uuid4())
        headers = {"x-api-key": self.api_key, "X-Correlation-Id": correlation_id, "Content-Type": "application/json"}
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.post(self.url, json={"readings": batch}, headers=headers, timeout=self.timeout_s)
            except requests.RequestException as exc:
                error = f"error de red: {exc}"
            else:
                if resp.status_code < 300:
                    return correlation_id
                if resp.status_code not in RETRYABLE_STATUS:
                    raise SendError(f"HTTP {resp.status_code} (correlation_id={correlation_id}): {resp.text[:300]}")
                error = f"HTTP {resp.status_code}"
            if attempt < self.max_retries:
                self.sleep(self._backoff(attempt))
        raise SendError(f"Reintentos agotados (correlation_id={correlation_id}): {error}")

    def _backoff(self, attempt: int) -> float:
        return self.backoff_base_s * (2**attempt) * (1 + random.random() / 2)
