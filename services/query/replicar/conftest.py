"""Permite `import service` en los tests de este servicio aunque cada servicio tenga su propio service.py.

También agrega `services/query/common` (query_common) y `services/shared` al path, igual que el zip de la Lambda.
"""
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
