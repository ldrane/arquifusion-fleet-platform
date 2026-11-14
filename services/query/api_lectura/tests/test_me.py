import copy
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
REPO = HERE.parents[4]
sys.path[:0] = [str(HERE.parents[1]), str(HERE.parents[2] / "common"), str(REPO / "services" / "shared")]

# Se importa aquí y no dentro del test: con la suite completa se resolvería al handler.py de otro servicio.
import handler  # noqa: E402
import service  # noqa: E402
from arquifusion_shared.errors import ApiError  # noqa: E402

FIXTURE = json.loads((REPO / "contracts" / "fixtures" / "api" / "get_me.event.json").read_text(encoding="utf-8"))


def test_precedencia_de_roles():
    assert service.resolve_role({"tecnico", "admin"}) == "admin"
    assert service.resolve_role({"otro"}) is None


def test_me_tecnico_desde_fixture():
    assert service.run(FIXTURE) == (
        {
            "user_id": "u-tec-07",
            "email": "tec07@demo.arquifusion.local",
            "role": "tecnico",
            "zone": "norte",
            "technician_id": "TEC-07",
        },
        {},
    )


def test_rol_global_sin_zona():
    ev = copy.deepcopy(FIXTURE)
    ev["requestContext"]["authorizer"]["claims"].update({"cognito:groups": "gerencia", "custom:zone": "*"})
    assert service.run(ev)[0]["zone"] is None


def _code(ev):
    with pytest.raises(ApiError) as e:
        service.run(ev)
    return e.value.status, e.value.code


def test_sin_grupo_403():
    ev = copy.deepcopy(FIXTURE)
    del ev["requestContext"]["authorizer"]["claims"]["cognito:groups"]
    assert _code(ev) == (403, "FORBIDDEN")


def test_sin_claims_401():
    ev = copy.deepcopy(FIXTURE)
    ev["requestContext"]["authorizer"] = {}
    assert _code(ev) == (401, "UNAUTHENTICATED")


def test_fixture_sin_prefijo_v1():
    assert FIXTURE["resource"] == "/me" and FIXTURE["requestContext"]["stage"] == "v1"


def test_ruta_desconocida_404():
    assert _code(dict(FIXTURE, resource="/nope")) == (404, "NOT_FOUND")


def test_handler_envelope():

    class Ctx:
        function_name, memory_limit_in_mb, invoked_function_arn, aws_request_id = (
            "api-lectura",
            256,
            "arn:aws:lambda:us-east-1:1:function:x",
            "req-1",
        )

    resp = handler.handler(FIXTURE, Ctx())
    assert resp["statusCode"] == 200
    assert resp["headers"]["X-Correlation-Id"] == "7c1e4b1a-0d2f-4a55-9c50-3b3f0a6f1e11"
    assert json.loads(resp["body"])["data"]["role"] == "tecnico"
