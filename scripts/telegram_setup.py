#!/usr/bin/env python3
"""Configura el webhook entrante de Telegram (TAREA-09).

Lee `bot_token` y `webhook_secret` del secreto `arquifusion/<stage>/telegram` (o de `.env.deploy`) y la URL
pública de la API de SSM `/arquifusion/<stage>/api/url`. Ejecuta `setWebhook` con
`allowed_updates=["message","callback_query"]` y muestra `getWebhookInfo` sin imprimir nunca el token.

Uso: python3 scripts/telegram_setup.py [--stage dev] [--api-url https://...]
"""

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.telegram.org/bot{token}/{method}"


def _env_file(name: str) -> str:
    env_file = ROOT / ".env.deploy"
    if not env_file.exists():
        return ""
    for line in env_file.read_text().splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _secret(stage: str) -> dict:
    """Secreto de Telegram desde Secrets Manager; si no hay AWS, cae a `.env.deploy`."""
    name = f"arquifusion/{stage}/telegram"
    try:
        import boto3

        raw = boto3.client("secretsmanager").get_secret_value(SecretId=name)["SecretString"]
        data = json.loads(raw)
    except Exception:  # noqa: BLE001 - el modo local usa .env.deploy
        data = {
            "bot_token": os.environ.get("TELEGRAM_BOT_TOKEN") or _env_file("TELEGRAM_BOT_TOKEN"),
            "webhook_secret": os.environ.get("TELEGRAM_WEBHOOK_SECRET") or _env_file("TELEGRAM_WEBHOOK_SECRET"),
        }
    if not data.get("bot_token"):
        raise SystemExit(f"Falta bot_token en el secreto {name} (o TELEGRAM_BOT_TOKEN)")
    if not data.get("webhook_secret"):
        raise SystemExit("Falta webhook_secret: define TELEGRAM_WEBHOOK_SECRET en .env.deploy y redeploya")
    return data


def _api_url(stage: str) -> str:
    if os.environ.get("API_URL"):
        return os.environ["API_URL"].rstrip("/")
    try:
        import boto3

        return boto3.client("ssm").get_parameter(Name=f"/arquifusion/{stage}/api/url")["Parameter"]["Value"].rstrip("/")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"No se pudo leer /arquifusion/{stage}/api/url: {type(exc).__name__}") from None


def call(token: str, method: str, payload: dict | None = None) -> dict:
    """POST a la Bot API. Los errores se reportan sin la URL (lleva el token)."""
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        API.format(token=token, method=method),
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:  # noqa: S310 - URL fija https
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:200]
        raise SystemExit(f"{method} HTTP {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise SystemExit(f"{method} sin conexión: {exc.reason}") from None


def main() -> int:
    parser = argparse.ArgumentParser(description="Configura el webhook de Telegram")
    parser.add_argument("--stage", default=os.environ.get("STAGE", "dev"))
    parser.add_argument("--api-url", default="", help="URL de API Gateway (por defecto se lee de SSM)")
    args = parser.parse_args()

    secret = _secret(args.stage)
    api_url = (args.api_url or _api_url(args.stage)).rstrip("/")
    webhook_url = f"{api_url}/telegram/webhook"

    result = call(secret["bot_token"], "setWebhook", {
        "url": webhook_url,
        "secret_token": secret["webhook_secret"],
        "allowed_updates": ["message", "callback_query"],
    })
    info = call(secret["bot_token"], "getWebhookInfo")
    data = info.get("result") or {}
    print(f"setWebhook: {'OK' if result.get('ok') else 'FALLA'}")
    print(f"url: {data.get('url') or webhook_url}")
    print(f"pending_update_count: {data.get('pending_update_count', 0)}")
    if data.get("last_error_message"):
        print(f"last_error: {data['last_error_message']}")
    if data.get("last_error_date"):
        print(f"last_error_date: {data['last_error_date']}")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
