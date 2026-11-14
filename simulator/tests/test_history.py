from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
from arquifusion_ml.lake import LAKE_COLUMNS

from simulator.history import FAILURES_FILE, generate_history, schedule_failures

END = datetime(2026, 11, 13, tzinfo=UTC)


@pytest.fixture(scope="module")
def history(tmp_path_factory, fleet):
    out = tmp_path_factory.mktemp("lake")
    summary = generate_history(fleet, 4, out, interval_min=60, seed=5, end=END)
    return out, summary


def test_parquet_columns_equal_lake_schema(history):
    out, _ = history
    files = list(out.glob("telemetry/**/*.parquet"))
    assert files
    for f in files:
        assert pq.read_schema(f).names == [c for c, _ in LAKE_COLUMNS]
        assert str(pq.read_schema(f).field("ts").type) == "timestamp[ms, tz=UTC]"


def test_partitions_follow_firehose_layout(history, fleet):
    out, summary = history
    parts = {f.parent.relative_to(out).as_posix() for f in out.glob("telemetry/**/*.parquet")}
    types = {m.machine_type for m in fleet}
    expected = {
        f"telemetry/operation_id=OP-01/dt=2026-11-{d:02d}/machine_type={t}" for d in range(9, 13) for t in types
    }
    assert parts == expected
    assert summary["rows"] == 4 * 24 * len(fleet)


def test_rows_land_in_their_day_partition(history):
    out, _ = history
    f = next(out.glob("telemetry/**/dt=2026-11-10/**/*.parquet"))
    df = pd.read_parquet(f)
    assert (df["ts"].dt.strftime("%Y-%m-%d") == "2026-11-10").all()


def test_failures_have_labeled_precursor(fleet):
    start = datetime(2026, 8, 15, tzinfo=UTC)
    events = schedule_failures(fleet, start, END, np.random.default_rng(1))
    assert len(events) > len(fleet) / 2
    assert {e.kind for e in events} >= {"degradacion", "combustible", "falla_subita", "grupal_zona"}
    for e in events:
        assert start <= e.precursor_start < e.failure_at <= e.repair_end <= END + (e.repair_end - e.failure_at)
    by_machine = {}
    for e in events:
        assert not any(e.overlaps(o) for o in by_machine.get(e.machine_id, []))
        by_machine.setdefault(e.machine_id, []).append(e)


def test_failures_file_and_labels_in_lake(tmp_path, fleet):
    generate_history(fleet, 30, tmp_path, interval_min=180, seed=2, end=END)
    failures = pd.read_parquet(tmp_path / FAILURES_FILE)
    lake = pd.concat(pd.read_parquet(f) for f in tmp_path.glob("telemetry/**/*.parquet"))
    labeled = lake[lake["sim_scenario"].notna()]
    assert not failures.empty and not labeled.empty
    assert set(labeled["sim_scenario"]) <= set(failures["kind"])
    assert lake["health_score"].isna().all() and lake["severity"].isna().all()


def test_history_is_deterministic(tmp_path, fleet):
    a = generate_history(fleet, 1, tmp_path / "a", interval_min=120, seed=9, end=END)
    b = generate_history(fleet, 1, tmp_path / "b", interval_min=120, seed=9, end=END)
    fa = sorted((tmp_path / "a").glob("telemetry/**/*.parquet"))
    fb = sorted((tmp_path / "b").glob("telemetry/**/*.parquet"))
    assert a["rows"] == b["rows"]
    assert all(pd.read_parquet(x).equals(pd.read_parquet(y)) for x, y in zip(fa, fb, strict=True))
