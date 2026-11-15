"""scripts/cognito_users.py contra un Cognito falso en memoria (moto-cognito exige joserfc, que no está en el venv)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cognito_users  # noqa: E402
import seed_data  # noqa: E402


class FakeCognito:
    """Solo las operaciones de cognito-idp que usa el script."""

    class exceptions:  # noqa: N801 (mismo nombre que boto3)
        class UserNotFoundException(Exception):
            pass

    def __init__(self, name="arquifusion-t-users"):
        self.pool = {"Id": "us-east-1_TEST", "Name": name}
        self.users, self.groups, self.passwords = {}, {}, {}

    def list_user_pools(self, MaxResults, NextToken=None):
        return {"UserPools": [self.pool]}

    def list_groups(self, UserPoolId, Limit):
        return {"Groups": [{"GroupName": g} for g in self.groups]}

    def create_group(self, UserPoolId, GroupName, Precedence):
        self.groups[GroupName] = Precedence

    def admin_get_user(self, UserPoolId, Username):
        if Username not in self.users:
            raise self.exceptions.UserNotFoundException(Username)
        u = self.users[Username]
        return {"UserAttributes": [{"Name": k, "Value": v} for k, v in u["attrs"].items()]}

    def list_users(self, UserPoolId):
        return {"Users": list(self.users)}

    def admin_create_user(self, UserPoolId, Username, UserAttributes, TemporaryPassword, MessageAction):
        assert MessageAction == "SUPPRESS"
        self.users[Username] = {"attrs": {a["Name"]: a["Value"] for a in UserAttributes}, "groups": set()}

    def admin_update_user_attributes(self, UserPoolId, Username, UserAttributes):
        self.users[Username]["attrs"].update({a["Name"]: a["Value"] for a in UserAttributes})

    def admin_set_user_password(self, UserPoolId, Username, Password, Permanent):
        assert Permanent
        self.passwords[Username] = Password

    def admin_list_groups_for_user(self, UserPoolId, Username):
        return {"Groups": [{"GroupName": g} for g in sorted(self.users[Username]["groups"])]}

    def admin_add_user_to_group(self, UserPoolId, Username, GroupName):
        assert GroupName in self.groups
        self.users[Username]["groups"].add(GroupName)

    def admin_remove_user_from_group(self, UserPoolId, Username, GroupName):
        self.users[Username]["groups"].discard(GroupName)


@pytest.fixture()
def pool():
    client = FakeCognito()
    yield client, client.pool["Id"]


def _attrs(client, pool_id, user):
    return {a["Name"]: a["Value"] for a in client.admin_get_user(UserPoolId=pool_id, Username=user)["UserAttributes"]}


def test_crea_staff_y_tecnicos_con_claims(pool, capsys):
    client, pool_id = pool
    assert cognito_users.main(["--stage", "t", "--password", "Demo-2026!x", "--create-groups"], client=client) == 0
    users = client.list_users(UserPoolId=pool_id)["Users"]
    assert len(users) == 5 + len(seed_data.TECHNICIANS)  # seed v4: 16 técnicos
    a = _attrs(client, pool_id, "u-tec-07")
    assert a["custom:technician_id"] == "TEC-07" and a["custom:zone"] == "norte"
    assert "custom:technician_id" not in _attrs(client, pool_id, "u-sup-01")
    assert _attrs(client, pool_id, "u-adm-01")["custom:zone"] == "*"
    groups = client.admin_list_groups_for_user(UserPoolId=pool_id, Username="u-tec-07")["Groups"]
    assert [g["GroupName"] for g in groups] == ["tecnico"]
    assert "Demo-2026!x" not in capsys.readouterr().out


def test_idempotente_y_corrige_grupo(pool):
    client, pool_id = pool
    cognito_users.main(
        ["--user-pool-id", pool_id, "--password", "Demo-2026!x", "--create-groups", "--only", "u-tec-07"], client=client
    )
    client.users["u-tec-07"]["groups"].add("admin")
    cognito_users.main(["--user-pool-id", pool_id, "--password", "Demo-2026!x", "--only", "u-tec-07"], client=client)
    groups = client.admin_list_groups_for_user(UserPoolId=pool_id, Username="u-tec-07")["Groups"]
    assert [g["GroupName"] for g in groups] == ["tecnico"]
    assert len(client.list_users(UserPoolId=pool_id)["Users"]) == 1


def test_sin_grupos_y_sin_create_groups_falla(pool):
    client, pool_id = pool
    with pytest.raises(SystemExit):
        cognito_users.main(["--user-pool-id", pool_id, "--password", "x"], client=client)


def test_usuarios_coinciden_con_el_seed():
    techs = {u["user_id"]: u for u in cognito_users.demo_users() if u["role"] == "tecnico"}
    assert techs["u-tec-07"]["technician_id"] == "TEC-07" and len(techs) == len(seed_data.TECHNICIANS)
