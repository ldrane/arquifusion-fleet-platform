"""Aísla los módulos de este servicio en los tests (cada servicio tiene su propio service.py)."""

import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path[:0] = [str(HERE), str(HERE / "tests")]
for mod in (
    "service",
    "handler",
    "gemini_client",
    "prompts",
    "ia_tasks",
    "ia_fallbacks",
    "ia_tools",
    "ia_assistant",
    "fakes",
):
    sys.modules.pop(mod, None)

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("POWERTOOLS_TRACE_DISABLED", "true")
