"""Capa 3: IsolationForest multivariado (RF-02.4, MH-AI-01, TRZ-05).

La versión activa está en SSM `/arquifusion/{stage}/model/active_version` y los artefactos en
`s3://<model_bucket>/models/isolation_forest/<version>/` (ver arquifusion_ml.model_store).
Si no hay versión activa o el artefacto falla, la capa 3 queda desactivada y `procesar` sigue con las capas 1 y 2.

Solo se puntúan las lecturas cuyo `state` está en `metadata.extra["scored_states"]` (las mismas con las que se
entrenó el modelo; ver services/analytics/retrain). El resto devuelve None y se evalúa con las capas 1 y 2.

Score de anomalía: `-model.score_samples(X)`, el score del paper original de Isolation Forest (0-1;
≈0.5 normal, cercano a 1 anómalo). `metadata.score_threshold` está en esa misma escala.
"""

import io
import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from arquifusion_ml.features import FEATURES, to_vector
from arquifusion_ml.model_store import ModelMetadata, metadata_key, model_key


@dataclass(frozen=True)
class MlResult:
    score: float  # 0-1, mayor = más anómalo
    risk: float  # 0-1, cuánto supera el umbral del modelo
    model_version: str


class ModelProvider:
    """Carga y cachea el modelo activo. Revisa la versión en SSM cada `ttl_s` segundos."""

    def __init__(
        self,
        get_active_version: Callable[[], str | None],
        read_object: Callable[[str], bytes],
        ttl_s: int = 300,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._get_active_version = get_active_version
        self._read_object = read_object
        self._ttl_s = ttl_s
        self._clock = clock
        self._checked_at = float("-inf")
        self._version: str | None = None
        self._model = None
        self._metadata: ModelMetadata | None = None

    def _refresh(self) -> None:
        now = self._clock()
        if now - self._checked_at < self._ttl_s:
            return
        self._checked_at = now
        version = self._get_active_version()
        if not version or version == self._version:
            return
        import joblib  # import diferido: el cold start sin modelo no paga sklearn

        metadata = ModelMetadata.from_dict(json.loads(self._read_object(metadata_key(version))))
        if tuple(metadata.features) != FEATURES:
            raise ValueError(f"El modelo {version} usa otras variables: {metadata.features}")
        self._model = joblib.load(io.BytesIO(self._read_object(model_key(version))))
        self._metadata = metadata
        self._version = version

    @property
    def version(self) -> str | None:
        return self._version

    def score(self, reading: dict) -> MlResult | None:
        """Score de una lectura, o None si no hay modelo activo."""
        self._refresh()
        if self._model is None or self._metadata is None:
            return None
        scored_states = self._metadata.extra.get("scored_states")
        if scored_states and reading.get("state") not in scored_states:
            return None
        score = float(-self._model.score_samples([to_vector(reading)])[0])
        threshold = self._metadata.score_threshold
        risk = max(0.0, min(1.0, (score - threshold) / max(1.0 - threshold, 1e-6)))
        return MlResult(score=score, risk=risk, model_version=self._metadata.model_version)
