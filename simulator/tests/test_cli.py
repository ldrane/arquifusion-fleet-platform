import json

import pytest

from simulator.cli import build_parser, main


def test_stream_dry_run_writes_valid_batches(tmp_path, schemas):
    from simulator.tests.contract import validate

    out = tmp_path / "batches.jsonl"
    main(
        [
            "stream",
            "--scenario",
            "degradacion",
            "--machine",
            "EX-001",
            "--rate",
            "600",
            "--duration",
            "0.005",
            "--dry-run",
            "--out",
            str(out),
        ]
    )
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert lines and all(1 <= len(b["readings"]) <= 100 for b in lines)
    for batch in lines:
        for r in batch["readings"]:
            validate(r, schemas["TelemetryReading"], schemas)


def test_stream_requires_credentials_without_dry_run(monkeypatch):
    monkeypatch.delenv("SIMULATOR_API_URL", raising=False)
    monkeypatch.delenv("SIMULATOR_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        main(["stream", "--duration", "1"])


def test_history_accepts_days_suffix():
    args = build_parser().parse_args(["history", "--days", "90d"])
    assert args.days == 90


def test_fleet_export(tmp_path):
    out = tmp_path / "fleet.json"
    main(["fleet", "--out", str(out)])
    assert len(json.loads(out.read_text())) == 84
