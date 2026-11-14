"""Carga de prompts versionados desde `prompts/` (TRZ-05: la versión del prompt viaja en cada respuesta).

Formato de cada archivo: primera línea `version: <id>`, una línea `---` y luego el texto del prompt.
Los prompts de tarea usan el marcador `{payload}`, que se reemplaza por el JSON de entrada.
"""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class Prompt:
    text: str
    version: str

    def render(self, payload_json: str) -> str:
        return self.text.replace("{payload}", payload_json)


@cache
def load(name: str) -> Prompt:
    """Lee `prompts/<name>.md`. Lanza FileNotFoundError si no existe (error de programación, no de la IA)."""
    raw = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    header, _, body = raw.partition("\n---\n")
    if not header.startswith("version:") or not body:
        raise ValueError(f"Prompt {name} sin cabecera 'version:' y separador '---'")
    return Prompt(text=body.strip(), version=header.removeprefix("version:").strip())
