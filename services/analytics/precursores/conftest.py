"""Aísla los módulos de este servicio en los tests y agrega analytics_common al path."""

import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE), str(HERE.parent / "common")]
for mod in ("service", "handler"):
    sys.modules.pop(mod, None)

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("POWERTOOLS_TRACE_DISABLED", "true")
