"""Minimal Keycloak Admin REST API client: just enough to authenticate and
pull a realm's partial-export. Deliberately not a general-purpose Keycloak
SDK."""

from __future__ import annotations

import requests


def get_admin_token(base_url: str, username: str, password: str, timeout: float = 15.0) -> str:
    response = requests.post(
        f"{base_url.rstrip('/')}/realms/master/protocol/openid-connect/token",
        data={
            "client_id": "admin-cli",
            "grant_type": "password",
            "username": username,
            "password": password,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("Keycloak did not return an access_token")
    return token


def partial_export(
    base_url: str,
    token: str,
    realm: str,
    export_clients: bool = True,
    export_groups_and_roles: bool = True,
    timeout: float = 30.0,
) -> dict:
    response = requests.post(
        f"{base_url.rstrip('/')}/admin/realms/{realm}/partial-export",
        params={
            "exportClients": str(export_clients).lower(),
            "exportGroupsAndRoles": str(export_groups_and_roles).lower(),
        },
        headers={"Authorization": f"Bearer {token}"},
        json={},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()
