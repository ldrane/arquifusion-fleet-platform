"""Capa 3: carga del IsolationForest desde S3 según la versión activa (RF-02.4, TRZ-05)."""

import io
import json

import joblib
import numpy as np
import pytest
from arquifusion_ml.features import FEATURES
from arquifusion_ml.model_store import ModelMetadata, metadata_key, model_key
from ingest_procesar.model import ModelProvider
from sklearn.ensemble import IsolationForest


def _artifacts(version="v1", features=FEATURES, threshold=0.55, scored_states=None):
    rng = np.random.default_rng(0)
    center = np.array([85, 4, 210, 35, 85, 1800, 6, 35 / 85])
    model = IsolationForest(n_estimators=50, random_state=0).fit(
        center + rng.normal(0, center * 0.02, (300, len(center)))
    )
    buf = io.BytesIO()
    joblib.dump(model, buf)
    md = ModelMetadata(version, "2026-11-13T00:00:00Z", list(features), threshold, 0.8, 0.7, 30.0, True)
    if scored_states:
        md.extra["scored_states"] = scored_states
    return {model_key(version): buf.getvalue(), metadata_key(version): json.dumps(md.to_dict()).encode()}


def test_no_active_version_disables_layer(base_reading):
    assert ModelProvider(lambda: None, lambda key: b"").score(base_reading) is None


def test_scores_outlier_higher_than_normal(base_reading):
    store = _artifacts()
    provider = ModelProvider(lambda: "v1", store.__getitem__)
    normal = dict(
        base_reading,
        temperature_c=85,
        vibration_mm_s=4,
        pressure_bar=210,
        fuel_rate_lph=35,
        load_pct=85,
        rpm=1800,
        speed_kmh=6,
    )
    outlier = dict(normal, temperature_c=120, vibration_mm_s=15, fuel_rate_lph=70)
    n, o = provider.score(normal), provider.score(outlier)
    assert n.model_version == "v1" and provider.version == "v1"
    assert o.score > n.score and o.risk > n.risk


def test_feature_mismatch_is_rejected(base_reading):
    provider = ModelProvider(lambda: "v1", _artifacts(features=["otra"]).__getitem__)
    with pytest.raises(ValueError):
        provider.score(base_reading)


def test_version_checked_with_cache(base_reading):
    store = _artifacts()
    calls = []
    clock = iter([0, 10, 20]).__next__

    def active():
        calls.append(1)
        return "v1"

    provider = ModelProvider(active, store.__getitem__, ttl_s=300, clock=clock)
    provider.score(base_reading)
    provider.score(base_reading)
    assert len(calls) == 1


def test_only_scored_states_are_scored(base_reading):
    provider = ModelProvider(lambda: "v1", _artifacts(scored_states=["operating"]).__getitem__)
    assert provider.score(dict(base_reading, state="operating")) is not None
    assert provider.score(dict(base_reading, state="idle")) is None
