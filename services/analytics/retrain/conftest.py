"""Permite `import service` en los tests de este servicio aunque cada servicio tenga su propio service.py."""

import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE), str(HERE.parent / "common")]
for mod in ("service", "handler", "retrain_model"):
    sys.modules.pop(mod, None)

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("POWERTOOLS_TRACE_DISABLED", "true")
