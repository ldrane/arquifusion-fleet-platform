"""Permite `import service`/`import handler` en los tests de este servicio y agrega los módulos comunes al path.

Igual que el zip de la Lambda: `query_common` (services/query/common) y `arquifusion_shared` (services/shared).
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
for extra in (HERE.parents[1] / "shared", HERE.parent / "common"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
if str(HERE) in sys.path:
    sys.path.remove(str(HERE))
sys.path.insert(0, str(HERE))
for mod in ("service", "handler"):
    sys.modules.pop(mod, None)

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("POWERTOOLS_TRACE_DISABLED", "true")
