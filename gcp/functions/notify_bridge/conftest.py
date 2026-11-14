"""Permite `import main` en los tests de esta función."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.modules.pop("main", None)
