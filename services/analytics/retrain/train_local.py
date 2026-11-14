"""Entrenamiento local sobre el historial del simulador (RF-13.2). Produce el primer modelo (v1).

Uso (desde la raíz del repo, tras `python -m simulator history ...`):
    .venv/bin/python services/analytics/retrain/train_local.py --lake data/lake --out build/models
    # opcional: subirlo y activarlo
    aws s3 cp --recursive build/models/v1 s3://<artifacts-bucket>/models/isolation_forest/v1/
    aws ssm put-parameter --name /arquifusion/<stage>/model/active_version --value v1 --type String --overwrite
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pandas as pd

sys.path[:0] = [str(Path(__file__).parent), str(Path(__file__).parents[1] / "common")]

import retrain_model  # noqa: E402
from arquifusion_ml.lake import TELEMETRY_PREFIX  # noqa: E402

COLUMNS = ["machine_id", "ts", "sim_scenario", "state", *retrain_model.RAW_FEATURES]


def main() -> None:
    parser = argparse.ArgumentParser(description="Entrena el IsolationForest con el lake local")
    parser.add_argument("--lake", type=Path, default=Path("data/lake"))
    parser.add_argument("--out", type=Path, default=Path("build/models"))
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()

    frame = pd.read_parquet(args.lake / TELEMETRY_PREFIX, columns=COLUMNS)
    failures_path = args.lake / "labels" / "failures.parquet"
    failures = pd.read_parquet(failures_path) if failures_path.exists() else None
    result = retrain_model.train(frame, failures, args.version, datetime.now(UTC))

    out = args.out / args.version
    out.mkdir(parents=True, exist_ok=True)
    joblib.dump(result.model, out / "model.joblib")
    (out / "metadata.json").write_text(json.dumps(result.metadata.to_dict(), indent=2))
    print(json.dumps({**result.metadata.api_view(), **result.metadata.extra, "out": str(out)}, indent=2))


if __name__ == "__main__":
    main()
