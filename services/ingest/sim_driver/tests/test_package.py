"""Guard de empaquetado de la imagen sim-driver (TAREA-07).

En AWS la Lambda fallaba con `Runtime.ImportModuleError: No module named 'arquifusion_shared'`
porque el Dockerfile no copiaba `services/shared`. Este test reproduce el "task root" de la
imagen (solo lo que el Dockerfile copia) y comprueba que `import handler` funciona ahí.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_DIR.parents[2]
DOCKERFILE = (SERVICE_DIR / "Dockerfile").read_text(encoding="utf-8")

PROBE = """
import json, os, sys
sys.path.insert(0, os.getcwd())
import arquifusion_shared
import handler
print(json.dumps({
    "shared": arquifusion_shared.__file__,
    "module": handler.handler.__module__,
    "callable": callable(handler.handler),
}))
"""


def test_dockerfile_installs_shared():
    assert "COPY services/shared" in DOCKERFILE
    assert "pip install" in DOCKERFILE and "/tmp/shared" in DOCKERFILE


def test_import_handler_from_task_root(tmp_path):
    task = tmp_path / "task"
    task.mkdir()
    shutil.copy2(SERVICE_DIR / "handler.py", task / "handler.py")
    shutil.copy2(SERVICE_DIR / "service.py", task / "service.py")
    shutil.copytree(REPO_ROOT / "simulator", task / "simulator")
    shutil.copytree(REPO_ROOT / "services" / "shared" / "arquifusion_shared", task / "arquifusion_shared")

    env = {
        "PATH": os.environ.get("PATH", ""),
        "AWS_DEFAULT_REGION": "us-east-1",
        "POWERTOOLS_TRACE_DISABLED": "true",
    }
    proc = subprocess.run(
        [sys.executable, "-I", "-c", PROBE],
        cwd=task,
        env=env,  # -I ignora PYTHONPATH; boto3/requests/numpy salen del venv
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    info = json.loads(proc.stdout)
    assert info["module"] == "handler"
    assert info["callable"] is True
    # Si el bundle no trae el paquete, gana el editable del venv y este assert falla.
    assert Path(info["shared"]).resolve().is_relative_to(task)
