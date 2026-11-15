#!/usr/bin/env python3
"""Sonda de la API de Gemini (TAREA-05): AI Studio vs Vertex AI express.

Lee `GEMINI_API_KEY` del entorno o de `.env.deploy` (nunca imprime la clave), llama a ambos endpoints con un
prompt mínimo y lista los modelos `flash` visibles. Exit 0 si al menos un endpoint responde 200.

Uso: python3 scripts/check_gemini.py [--model MODEL] [--vertex-model MODEL]
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

AISTUDIO_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
VERTEX_URL = "https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent"
LIST_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-flash-lite-latest"
DEFAULT_VERTEX_MODEL = "gemini-2.5-flash-lite"
ROOT = Path(__file__).resolve().parents[1]


def api_key() -> str:
    """Clave del entorno o de `.env.deploy` (se lee sin imprimirla)."""
    key = os.environ.get("GEMINI_API_KEY", "")
    env_file = ROOT / ".env.deploy"
    if not key and env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                key = line.split("=", 1)[1]
                break
    return key.strip().strip('"').strip("'")


def post(url: str, key: str, body: dict, timeout_s: float = 20) -> tuple[int, dict | str, float]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:  # noqa: S310 (URL fija https)
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read(), exc.code
    except Exception as exc:  # noqa: BLE001 (la sonda reporta cualquier falla)
        return 0, f"{type(exc).__name__}: {exc}", (time.monotonic() - started) * 1000
    latency = (time.monotonic() - started) * 1000
    try:
        return status, json.loads(raw or b"{}"), latency
    except ValueError:
        return status, raw.decode(errors="replace")[:200], latency


def probe(name: str, url: str, model: str, key: str) -> bool:
    body = {
        "contents": [{"role": "user", "parts": [{"text": "Responde solo: OK"}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 8},
    }
    status, payload, latency = post(url.format(model=model), key, body)
    ok = status == 200 and isinstance(payload, dict) and bool(payload.get("candidates"))
    detail = ""
    if not ok and isinstance(payload, dict):
        detail = str(payload.get("error", {}).get("message", ""))[:120]
    print(f"{name:<12} {model:<26} HTTP {status:<4} {latency:7.0f} ms  {'OK' if ok else 'FALLA'} {detail}".rstrip())
    return ok


def list_models(key: str) -> None:
    request = urllib.request.Request(LIST_URL, headers={"x-goog-api-key": key})
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:  # noqa: S310
            data = json.loads(resp.read() or b"{}")
    except Exception as exc:  # noqa: BLE001
        print(f"modelos       lista no disponible: {type(exc).__name__}")
        return
    names = [m.get("name", "").removeprefix("models/") for m in data.get("models", [])]
    flash = [n for n in names if "flash" in n][:5]
    print("modelos flash:", ", ".join(flash) or "(ninguno)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sonda AI Studio / Vertex express")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--vertex-model", default=DEFAULT_VERTEX_MODEL)
    args = parser.parse_args()
    key = api_key()
    if not key:
        print("Falta GEMINI_API_KEY (entorno o .env.deploy)", file=sys.stderr)
        return 2
    print(f"key: {key[:3]}… ({len(key)} caracteres)")
    ok = probe("AI Studio", AISTUDIO_URL, args.model, key)
    ok = probe("Vertex", VERTEX_URL, args.vertex_model, key) or ok
    list_models(key)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
