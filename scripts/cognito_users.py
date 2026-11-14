#!/usr/bin/env python3
"""Usuarios demo de Cognito (dueña: Persona C; RNF-08, contratos.md §2.1, #8).

Crea (o actualiza) los usuarios del runbook con username legible (`cognito:username` = user_id de la plataforma),
su grupo (= rol) y los atributos `custom:zone` y `custom:technician_id`. Los técnicos salen del seed
(`seed_data.build_technicians()`): `u-tec-XX` -> `custom:technician_id = TEC-XX`, `custom:zone` = zona del técnico.

Uso (desde la raíz del repo; el User Pool y los 6 grupos los crea B en infra/base):
  python scripts/cognito_users.py --stage dev --password '<Demo-2026!>'                 # busca el pool por nombre
  python scripts/cognito_users.py --user-pool-id us-east-1_XXXX --password '...'       # pool explícito
  python scripts/cognito_users.py --stage c --password '...' --create-groups           # lab personal sin grupos
  python scripts/cognito_users.py --stage dev --only u-tec-07 --password '...'         # un solo usuario

Idempotente: si el usuario existe, actualiza atributos, contraseña y grupo. La contraseña queda PERMANENTE
(sin desafío NEW_PASSWORD_REQUIRED) y nunca se imprime. También acepta la variable DEMO_PASSWORD.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seed_data  # noqa: E402

ROLES = ("operador", "tecnico", "mantenimiento", "supervisor", "admin", "gerencia")
ROLE_PRECEDENCE = ("admin", "gerencia", "supervisor", "mantenimiento", "tecnico", "operador")
GLOBAL_ZONE = "*"

# Usuarios no técnicos del runbook (docs/h0-persona-c.md, frontend/src/demo/data.ts DEMO_USERS)
STAFF = [
    {"user_id": "u-op-01", "role": "operador", "zone": "norte", "email": "op01@demo.arquifusion.local", "name": "Rosa Quispe"},
    {"user_id": "u-mant-01", "role": "mantenimiento", "zone": GLOBAL_ZONE, "email": "mant01@demo.arquifusion.local", "name": "Carmen Rojas"},
    {"user_id": "u-sup-01", "role": "supervisor", "zone": "norte", "email": "sup01@demo.arquifusion.local", "name": "Luis Paredes"},
    {"user_id": "u-adm-01", "role": "admin", "zone": GLOBAL_ZONE, "email": "adm01@demo.arquifusion.local", "name": "Elena Rostova"},
    {"user_id": "u-ger-01", "role": "gerencia", "zone": GLOBAL_ZONE, "email": "ger01@demo.arquifusion.local", "name": "Miguel Salazar"},
]


def demo_users() -> list[dict]:
    """Staff + un usuario por técnico del seed (12)."""
    techs = [
        {
            "user_id": t["user_id"],
            "role": "tecnico",
            "zone": t["zone"],
            "email": f"tec{t['technician_id'].split('-')[1]}@demo.arquifusion.local",
            "name": t["name"],
            "technician_id": t["technician_id"],
        }
        for t in seed_data.build_technicians()
    ]
    return STAFF + techs


def attributes(user: dict) -> list[dict]:
    attrs = {
        "email": user["email"],
        "email_verified": "true",
        "name": user["name"],
        "custom:zone": user["zone"],
    }
    if user.get("technician_id"):
        attrs["custom:technician_id"] = user["technician_id"]
    return [{"Name": k, "Value": v} for k, v in attrs.items()]


def find_pool(client, stage: str) -> str:
    """Pool cuyo nombre empieza con `arquifusion-{stage}` (convención §9). Falla si hay 0 o más de 1."""
    prefix = f"arquifusion-{stage}"
    pools, token = [], None
    while True:
        kwargs: dict[str, Any] = {"MaxResults": 60}
        if token:
            kwargs["NextToken"] = token
        page = client.list_user_pools(**kwargs)
        pools += [p for p in page.get("UserPools", []) if p["Name"].startswith(prefix)]
        token = page.get("NextToken")
        if not token:
            break
    if len(pools) != 1:
        names = [p["Name"] for p in pools]
        sys.exit(f"Esperaba 1 User Pool con prefijo {prefix}, encontré {names}. Usa --user-pool-id.")
    return pools[0]["Id"]


def ensure_groups(client, pool_id: str, create: bool) -> None:
    existing = {g["GroupName"] for g in client.list_groups(UserPoolId=pool_id, Limit=60).get("Groups", [])}
    missing = [r for r in ROLES if r not in existing]
    if not missing:
        return
    if not create:
        sys.exit(f"Faltan grupos {missing} en el pool (los crea B en infra/base). Usa --create-groups solo en tu lab.")
    for role in missing:
        # Precedencia: admin = 0 (mayor), igual que arquifusion_shared.rbac.ROLE_PRECEDENCE
        client.create_group(UserPoolId=pool_id, GroupName=role, Precedence=ROLE_PRECEDENCE.index(role))
        print(f"  grupo {role}: creado")


def upsert_user(client, pool_id: str, user: dict, password: str) -> str:
    """Crea o actualiza el usuario. Devuelve 'creado' o 'actualizado'."""
    username = user["user_id"]
    try:
        client.admin_get_user(UserPoolId=pool_id, Username=username)
        client.admin_update_user_attributes(UserPoolId=pool_id, Username=username, UserAttributes=attributes(user))
        result = "actualizado"
    except client.exceptions.UserNotFoundException:
        client.admin_create_user(
            UserPoolId=pool_id, Username=username, UserAttributes=attributes(user),
            TemporaryPassword=password, MessageAction="SUPPRESS",
        )
        result = "creado"
    client.admin_set_user_password(UserPoolId=pool_id, Username=username, Password=password, Permanent=True)
    current = {g["GroupName"] for g in client.admin_list_groups_for_user(UserPoolId=pool_id, Username=username).get("Groups", [])}
    for extra in current - {user["role"]}:
        client.admin_remove_user_from_group(UserPoolId=pool_id, Username=username, GroupName=extra)
    if user["role"] not in current:
        client.admin_add_user_to_group(UserPoolId=pool_id, Username=username, GroupName=user["role"])
    return result


def main(argv: list[str] | None = None, client=None) -> int:
    parser = argparse.ArgumentParser(description="Usuarios demo de Cognito (Persona C)")
    parser.add_argument("--stage", help="busca el pool arquifusion-<stage>*")
    parser.add_argument("--user-pool-id")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--password", default=os.environ.get("DEMO_PASSWORD"), help="o variable DEMO_PASSWORD")
    parser.add_argument("--only", action="append", help="user_id a procesar (repetible)")
    parser.add_argument("--create-groups", action="store_true", help="crea los 6 grupos si faltan (solo lab personal)")
    args = parser.parse_args(argv)
    if not args.password:
        parser.error("falta --password (o DEMO_PASSWORD)")
    if not (args.user_pool_id or args.stage):
        parser.error("indica --user-pool-id o --stage")
    if client is None:
        import boto3

        client = boto3.client("cognito-idp", region_name=args.region)
    pool_id = args.user_pool_id or find_pool(client, args.stage)
    ensure_groups(client, pool_id, args.create_groups)
    users = [u for u in demo_users() if not args.only or u["user_id"] in args.only]
    for user in users:
        result = upsert_user(client, pool_id, user, args.password)
        extra = f" technician_id={user['technician_id']}" if user.get("technician_id") else ""
        print(f"  {user['user_id']:<10} {user['role']:<13} zone={user['zone']:<6}{extra}  {result}")
    print(f"Usuarios OK: {len(users)} en {pool_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
