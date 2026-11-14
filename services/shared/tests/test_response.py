import json
from decimal import Decimal

from arquifusion_shared.errors import NotFound
from arquifusion_shared.response import error, ok


def test_ok_envelope():
    body = json.loads(ok({"a": 1}, "cid")["body"])
    assert body == {"data": {"a": 1}, "meta": {}}


def test_error_envelope():
    r = error(NotFound("no existe"), "cid")
    assert r["statusCode"] == 404
    assert json.loads(r["body"])["error"]["code"] == "NOT_FOUND"


def test_cors_en_exito_y_error(monkeypatch):
    monkeypatch.setenv("CORS_ORIGIN", "https://d123.cloudfront.net")
    for r in (ok({}, "cid"), error(NotFound("x"), "cid")):
        h = r["headers"]
        assert h["Access-Control-Allow-Origin"] == "https://d123.cloudfront.net"
        assert h["Access-Control-Allow-Headers"] == "Authorization,Content-Type,X-Correlation-Id,X-Api-Key"
        assert h["Access-Control-Allow-Methods"] == "GET,POST,PUT,OPTIONS"
        assert h["Access-Control-Expose-Headers"] == "X-Correlation-Id"
        assert h["X-Correlation-Id"] == "cid"


def test_cors_por_defecto_asterisco(monkeypatch):
    monkeypatch.delenv("CORS_ORIGIN", raising=False)
    assert ok({}, "cid")["headers"]["Access-Control-Allow-Origin"] == "*"


def test_decimal_sale_como_numero():
    data = {"entero": Decimal("42"), "entero_con_punto": Decimal("3.0"), "real": Decimal("0.87"), "lista": [Decimal("1")]}
    raw = ok(data, "cid")["body"]
    body = json.loads(raw)["data"]
    assert body == {"entero": 42, "entero_con_punto": 3, "real": 0.87, "lista": [1]}
    assert isinstance(body["entero"], int) and isinstance(body["real"], float)
    assert '"42"' not in raw
