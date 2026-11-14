import json

from arquifusion_shared.errors import NotFound
from arquifusion_shared.response import error, ok


def test_ok_envelope():
    body = json.loads(ok({"a": 1}, "cid")["body"])
    assert body == {"data": {"a": 1}, "meta": {}}


def test_error_envelope():
    r = error(NotFound("no existe"), "cid")
    assert r["statusCode"] == 404
    assert json.loads(r["body"])["error"]["code"] == "NOT_FOUND"
