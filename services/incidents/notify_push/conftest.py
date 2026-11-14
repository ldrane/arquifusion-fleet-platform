"""Permite `import service` en los tests de este servicio.

El zip de la Lambda trae `gcp_auth.py` (de notificar) y `notify_bridge.py` (gcp/functions/notify_bridge/main.py);
aquí se cargan desde su ubicación original para no duplicar código.
"""

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[2]

for mod in ("service", "handler", "gcp_auth", "gcp_rest", "notify_bridge"):
    sys.modules.pop(mod, None)
sys.path.insert(0, str(HERE.parent / "notificar"))  # gcp_auth
sys.path.insert(0, str(HERE))

MAIN = ROOT / "gcp" / "functions" / "notify_bridge" / "main.py"
_spec = importlib.util.spec_from_file_location("notify_bridge", MAIN)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
sys.modules["notify_bridge"] = _mod
