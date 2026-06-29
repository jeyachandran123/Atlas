"""Integration tests for repository management API."""

from __future__ import annotations

import os

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_connect_repository(
    client: AsyncClient, developer_token: str, tmp_path
) -> None:
    """Connect a local repository."""
    response = await client.post(
        "/api/v1/repositories",
        json={
            "name": "My Test Repo",
            "local_path": str(tmp_path),
            "provider": "local",
        },
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "My Test Repo"
    assert body["provider"] == "local"
    assert body["index_status"] in ("pending", "indexing")
    assert "id" in body


@pytest.mark.asyncio
async def test_connect_repository_invalid_path(
    client: AsyncClient, developer_token: str
) -> None:
    """Connecting a non-existent path should return 400."""
    response = await client.post(
        "/api/v1/repositories",
        json={
            "name": "Bad Repo",
            "local_path": "/path/that/does/not/exist/xyz123",
            "provider": "local",
        },
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_repositories(
    client: AsyncClient, developer_token: str, tmp_path
) -> None:
    # Connect a repo first
    await client.post(
        "/api/v1/repositories",
        json={"name": "Listed Repo", "local_path": str(tmp_path)},
        headers={"Authorization": f"Bearer {developer_token}"},
    )

    response = await client.get(
        "/api/v1/repositories",
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert response.status_code == 200
    repos = response.json()
    assert isinstance(repos, list)
    assert any(r["name"] == "Listed Repo" for r in repos)


@pytest.mark.asyncio
async def test_get_repository_by_id(
    client: AsyncClient, developer_token: str, tmp_path
) -> None:
    # Create
    create_resp = await client.post(
        "/api/v1/repositories",
        json={"name": "Get By ID", "local_path": str(tmp_path)},
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    repo_id = create_resp.json()["id"]

    # Get
    response = await client.get(
        f"/api/v1/repositories/{repo_id}",
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert response.status_code == 200
    assert response.json()["id"] == repo_id


@pytest.mark.asyncio
async def test_get_nonexistent_repository(
    client: AsyncClient, developer_token: str
) -> None:
    response = await client.get(
        "/api/v1/repositories/00000000-0000-0000-0000-000000000000",
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_repository_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/repositories")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_sync_repository(
    client: AsyncClient, developer_token: str, tmp_path
) -> None:
    # Connect a repo
    create_resp = await client.post(
        "/api/v1/repositories",
        json={"name": "Sync Repo", "local_path": str(tmp_path)},
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    repo_id = create_resp.json()["id"]

    # Trigger sync
    sync_resp = await client.post(
        f"/api/v1/repositories/{repo_id}/sync",
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert sync_resp.status_code == 200
    body = sync_resp.json()
    assert body["repo_id"] == repo_id
    assert body["job_type"] == "incremental"
    assert body["status"] == "queued"
