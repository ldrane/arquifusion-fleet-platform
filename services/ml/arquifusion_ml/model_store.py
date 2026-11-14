"""Artefactos del modelo IsolationForest en S3 y su metadata (RF-13.2, TRZ-05, MH-AI-04).

Escribe `retrain`; lee `procesar`. La versión activa vive en SSM `/arquifusion/{stage}/model/active_version`.
"""

from dataclasses import asdict, dataclass, field

MODEL_PREFIX = "models/isolation_forest"


def model_key(version: str) -> str:
    return f"{MODEL_PREFIX}/{version}/model.joblib"


def metadata_key(version: str) -> str:
    return f"{MODEL_PREFIX}/{version}/metadata.json"


def active_version_param(stage: str) -> str:
    return f"/arquifusion/{stage}/model/active_version"


@dataclass
class ModelMetadata:
    """Metadata del modelo. Sus campos de métricas son el `data` de `GET /v1/ml/model`."""

    model_version: str
    trained_at: str  # ISO 8601 UTC
    features: list[str]  # debe ser igual a arquifusion_ml.features.FEATURES
    score_threshold: float  # score de anomalía (0-1) a partir del cual la capa ML marca anomalía
    precision: float
    recall: float
    mean_lead_time_hours: float  # anticipación media frente a la falla etiquetada
    promoted: bool
    training_rows: int = 0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModelMetadata":
        return cls(**d)

    def api_view(self) -> dict:
        """Forma exacta de `data` en `GET /v1/ml/model`."""
        keys = ("model_version", "trained_at", "precision", "recall", "mean_lead_time_hours", "promoted")
        return {k: getattr(self, k) for k in keys}
