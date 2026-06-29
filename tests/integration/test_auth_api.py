"""Integration tests for authentication endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_current_user(client: AsyncClient, developer_token: str) -> None:
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "dev@test.com"
    assert body["role"] == "developer"


@pytest.mark.asyncio
async def test_get_me_without_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me_with_bad_token(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer totally.fake.token"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_can_create_api_key(client: AsyncClient, admin_token: str) -> None:
    response = await client.post(
        "/api/v1/auth/keys",
        json={"name": "CI Key", "scopes": ["read"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 201
    body = response.json()
    assert "key" in body
    assert body["key"].startswith("aic-")
    assert body["details"]["name"] == "CI Key"


@pytest.mark.asyncio
async def test_developer_cannot_create_api_key(
    client: AsyncClient, developer_token: str
) -> None:
    """Creating API keys requires admin role."""
    response = await client.post(
        "/api/v1/auth/keys",
        json={"name": "Dev Key", "scopes": ["read"]},
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_api_keys(client: AsyncClient, admin_token: str) -> None:
    # Create a key first
    await client.post(
        "/api/v1/auth/keys",
        json={"name": "List Test Key"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    response = await client.get(
        "/api/v1/auth/keys",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert response.status_code == 200
    keys = response.json()
    assert isinstance(keys, list)
    assert any(k["name"] == "List Test Key" for k in keys)


@pytest.mark.asyncio
async def test_revoke_api_key(client: AsyncClient, admin_token: str) -> None:
    # Create key
    create_resp = await client.post(
        "/api/v1/auth/keys",
        json={"name": "Revoke Me"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    key_id = create_resp.json()["details"]["id"]

    # Revoke
    revoke_resp = await client.delete(
        f"/api/v1/auth/keys/{key_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert revoke_resp.status_code == 204

    # Should no longer appear in list
    list_resp = await client.get(
        "/api/v1/auth/keys",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    key_ids = [k["id"] for k in list_resp.json()]
    assert key_id not in key_ids


@pytest.mark.asyncio
async def test_health_endpoint_public(client: AsyncClient) -> None:
    """Health endpoint must be publicly accessible — used by load balancers."""
    response = await client.get("/api/v1/admin/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
