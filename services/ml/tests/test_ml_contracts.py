import json
from pathlib import Path

from arquifusion_ml.features import FEATURES, to_vector
from arquifusion_ml.insights import LATEST, items
from arquifusion_ml.lake import LAKE_COLUMNS, flatten_reading, partition_prefix
from arquifusion_ml.model_store import ModelMetadata, model_key

FIXTURE = Path(__file__).parents[3] / "contracts/fixtures/api/telemetry_batch.json"


def reading() -> dict:
    return json.loads(FIXTURE.read_text())["readings"][0]


def test_vector_matches_features():
    assert len(to_vector(reading())) == len(FEATURES)


def test_flatten_reading_has_lake_columns():
    row = flatten_reading(reading())
    assert set(row) == {c for c, _ in LAKE_COLUMNS}
    assert row["zone"] == "norte" and row["ts"] == "2026-11-13T10:14:55Z"


def test_partition_prefix():
    assert partition_prefix("OP-01", "2026-11-13", "excavator") == (
        "telemetry/operation_id=OP-01/dt=2026-11-13/machine_type=excavator/"
    )


def test_model_metadata_api_view():
    md = ModelMetadata("v1", "2026-11-13T00:00:00Z", list(FEATURES), 0.6, 0.8, 0.7, 36.0, True)
    expected = {"model_version", "trained_at", "precision", "recall", "mean_lead_time_hours", "promoted"}
    assert set(md.api_view()) == expected
    assert model_key("v1") == "models/isolation_forest/v1/model.joblib"


def test_insights_items_write_latest():
    out = items("ml_model", "2026-11-13", {}, "2026-11-13T05:00:00Z", "cid")
    assert [i["sk"] for i in out] == ["2026-11-13", LATEST]
