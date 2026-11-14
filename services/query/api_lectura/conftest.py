"""Permite `import service` en los tests de este servicio aunque cada servicio tenga su propio service.py.

También agrega `services/query/common` (query_common) y `services/shared` (arquifusion_shared) al path,
igual que el zip de la Lambda (infra/query).
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
for extra in (HERE.parents[1] / "shared", HERE.parent / "common", HERE):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
sys.path.remove(str(HERE))
sys.path.insert(0, str(HERE))
for mod in ("service", "handler"):
    sys.modules.pop(mod, None)
