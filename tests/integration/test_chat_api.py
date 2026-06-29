"""Integration tests for the chat API."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_conversation(client: AsyncClient, developer_token: str) -> None:
    response = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Test conversation"},
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Test conversation"
    assert "id" in body


@pytest.mark.asyncio
async def test_list_conversations_empty(client: AsyncClient, developer_token: str) -> None:
    response = await client.get(
        "/api/v1/chat/conversations",
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_send_message(client: AsyncClient, developer_token: str) -> None:
    response = await client.post(
        "/api/v1/chat/message",
        json={"message": "How does authentication work?"},
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "content" in body
    assert "conversation_id" in body
    assert body["content"] == "MOCKED_AI_RESPONSE"
    assert body["agent_used"] == "coding_agent"


@pytest.mark.asyncio
async def test_send_message_creates_conversation(client: AsyncClient, developer_token: str) -> None:
    """Sending a message without conversation_id should auto-create one."""
    response = await client.post(
        "/api/v1/chat/message",
        json={"message": "Explain this code"},
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] is not None

    # Verify conversation appears in list
    list_resp = await client.get(
        "/api/v1/chat/conversations",
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert list_resp.status_code == 200
    conv_ids = [c["id"] for c in list_resp.json()]
    assert body["conversation_id"] in conv_ids


@pytest.mark.asyncio
async def test_send_message_continues_conversation(
    client: AsyncClient, developer_token: str
) -> None:
    """Messages in the same conversation should accumulate."""
    # Create conversation
    create_resp = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Test"},
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    conv_id = create_resp.json()["id"]

    # First message
    await client.post(
        "/api/v1/chat/message",
        json={"message": "Hello", "conversation_id": conv_id},
        headers={"Authorization": f"Bearer {developer_token}"},
    )

    # Second message in same conversation
    resp = await client.post(
        "/api/v1/chat/message",
        json={"message": "Continue", "conversation_id": conv_id},
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["conversation_id"] == conv_id


@pytest.mark.asyncio
async def test_get_conversation_messages(
    client: AsyncClient, developer_token: str
) -> None:
    # Create conv and send a message
    create_resp = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Msgs test"},
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    conv_id = create_resp.json()["id"]

    await client.post(
        "/api/v1/chat/message",
        json={"message": "First message", "conversation_id": conv_id},
        headers={"Authorization": f"Bearer {developer_token}"},
    )

    # Get messages
    resp = await client.get(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) >= 2  # user + assistant
    roles = [m["role"] for m in messages]
    assert "user" in roles
    assert "assistant" in roles


@pytest.mark.asyncio
async def test_chat_requires_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/chat/message",
        json={"message": "Hello"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_requires_non_empty_message(
    client: AsyncClient, developer_token: str
) -> None:
    response = await client.post(
        "/api/v1/chat/message",
        json={"message": ""},
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_messages_wrong_user(
    client: AsyncClient, developer_token: str, admin_token: str
) -> None:
    """User A should not see User B's conversation messages."""
    # Developer creates conversation
    create_resp = await client.post(
        "/api/v1/chat/conversations",
        json={"title": "Private"},
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    conv_id = create_resp.json()["id"]

    # Admin tries to access it — should be denied
    resp = await client.get(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 403
