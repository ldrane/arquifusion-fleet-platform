import pytest
from arquifusion_shared import config, correlation, rbac
from arquifusion_shared.errors import Forbidden


def ev(groups="tecnico", **claims):
    return {
        "httpMethod": "GET",
        "headers": {},
        "requestContext": {"authorizer": {"claims": {"cognito:groups": groups, **claims}}},
    }


def test_rol_por_precedencia():
    assert rbac.role(ev("tecnico,supervisor")) == "supervisor"
    assert rbac.role(ev("operador")) == "operador"
    assert rbac.role(ev("")) is None


def test_require_rol():
    rbac.require(ev("tecnico"), "tecnico", "mantenimiento")
    with pytest.raises(Forbidden):
        rbac.require(ev("operador"), "tecnico")


def test_require_zona():
    rbac.require(ev("supervisor", **{"custom:zone": "norte"}), "supervisor", zone="norte")
    rbac.require(ev("admin", **{"custom:zone": "*"}), "admin", zone="sur")
    rbac.require(ev("admin"), "admin", zone="sur")  # rol global sin atributo = global
    with pytest.raises(Forbidden):
        rbac.require(ev("supervisor", **{"custom:zone": "norte"}), "supervisor", zone="sur")


def test_actor_y_claims_de_tecnico():
    e = ev("tecnico", **{"cognito:username": "u-tec-07", "custom:technician_id": "TEC-07"})
    assert rbac.actor(e) == {"type": "user", "user_id": "u-tec-07", "role": "tecnico"}
    assert rbac.technician_id(e) == "TEC-07"


def test_config_table(monkeypatch):
    monkeypatch.setenv("TABLE_NOTIFICATION_RULES", "arquifusion-dev-notification-rules")
    assert config.table("notification-rules") == "arquifusion-dev-notification-rules"
    assert config.table_env("maintenance-records") == "TABLE_MAINTENANCE_RECORDS"
    with pytest.raises(KeyError):
        config.table("insights")


def test_correlation_from_any():
    assert correlation.from_any({"httpMethod": "GET", "headers": {"x-correlation-id": "a"}}) == "a"
    assert correlation.from_any({"detail-type": "X", "detail": {"correlation_id": "b"}}) == "b"
    assert correlation.from_any({"correlation_id": "c"}) == "c"
    assert correlation.from_any({})


def test_f11_roles_de_zona_sin_zona_son_forbidden():
    for r in ("supervisor", "tecnico", "operador"):
        with pytest.raises(Forbidden):
            rbac.zone(ev(r))
        with pytest.raises(Forbidden):
            rbac.zone(ev(r, **{"custom:zone": "  "}))
        assert rbac.zone(ev(r, **{"custom:zone": "*"})) is None
        assert rbac.zone(ev(r, **{"custom:zone": "Norte"})) == "norte"
    with pytest.raises(Forbidden):
        rbac.require(ev("supervisor"), "supervisor", zone="sur")


def test_f11_roles_globales_sin_zona_siguen_globales():
    for r in ("admin", "gerencia", "mantenimiento"):
        assert rbac.zone(ev(r)) is None


def test_f35_correlation_id_validado():
    mk = lambda v: {"httpMethod": "GET", "headers": {"X-Correlation-Id": v}}  # noqa: E731
    assert correlation.from_any(mk("abc-123-DEF")) == "abc-123-DEF"
    for bad in ("a\nb", "x" * 65, "con espacio", "a;b", ""):
        out = correlation.from_any(mk(bad))
        assert out != bad and len(out) == 36
