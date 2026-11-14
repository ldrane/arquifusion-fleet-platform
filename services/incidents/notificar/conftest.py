"""Permite `import service` en los tests de este servicio aunque cada servicio tenga su propio service.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
for mod in ("service", "handler", "gcp_auth"):
    sys.modules.pop(mod, None)
