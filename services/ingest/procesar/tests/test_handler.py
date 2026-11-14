"""El handler arma sus dependencias desde variables de entorno sin llamar a AWS al importar."""

import importlib
import sys

ENV = {
    "STAGE": "test",
    "TABLE_MACHINES": "m",
    "TABLE_MACHINE_STATE": "s",
    "TABLE_IDEMPOTENCY": "i",
    "TABLE_ANOMALIES": "a",
    "EVENT_BUS_NAME": "b",
    "FIREHOSE_STREAM": "f",
    "MODEL_BUCKET": "k",
    "AWS_DEFAULT_REGION": "us-east-1",
    "POWERTOOLS_METRICS_NAMESPACE": "ArquiFusion",
}


def test_handler_imports_with_env(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    sys.modules.pop("handler", None)
    handler = importlib.import_module("handler")
    assert callable(handler.handler)
