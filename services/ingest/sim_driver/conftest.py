"""Aísla `service`/`handler` y deja importable el paquete `simulator` de la raíz del repo."""

import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE), str(HERE.parents[2])]
for mod in ("service", "handler"):
    sys.modules.pop(mod, None)

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("POWERTOOLS_TRACE_DISABLED", "true")
