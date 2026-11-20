"""The voice API: who may start a session, and what a finished turn leaves behind."""

from __future__ import annotations

import uuid

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.config import get_settings
from app.db.models import Conversation, Message
from app.voice import service
from app.voice.search import TOOL_DECLARATION


def turn(role: str, text: str, turn_id: str | None = None) -> dict:
    return {"id": turn_id or str(uuid.uuid4()), "role": role, "text": text}


@pytest.fixture
def memory(monkeypatch) -> list[tuple]:
    saved: list[tuple] = []

    async def push(user_id, conversation_id, role, content, *a, **k):  # noqa: ANN001, ANN002, ANN003
        saved.append((user_id, conversation_id, role, content))

    monkeypatch.setattr("app.api.v1.voice.router.push_session_message", push)
    return saved


handles: list[str | None] = []
tools_seen: list[list[dict] | None] = []


@pytest.fixture
def minted(monkeypatch) -> list[str]:
    instructions: list[str] = []
    handles.clear()
    tools_seen.clear()

    async def mint(
        system_instruction: str, resume_handle: str | None = None, tools: list[dict] | None = None
    ) -> service.LiveToken:
        instructions.append(system_instruction)
        handles.append(resume_handle)
        tools_seen.append(tools)
        return service.LiveToken(
            token="auth_tokens/abc",
            model="models/gemini-test-live",
            websocket_url="wss://example.test/live",
            expires_at="2026-11-02T10:30:00Z",
        )

    monkeypatch.setattr("app.api.v1.voice.router.mint_live_token", mint)
    return instructions


async def make_conversation(sk_session, owner) -> Conversation:
    conversation = Conversation(user_id=owner.id, title="Earlier chat")
    sk_session.add(conversation)
    await sk_session.commit()
    return conversation


class TestConfig:
    async def test_a_configured_deployment_says_enabled(
        self, sk_client, auth, monkeypatch
    ) -> None:
        monkeypatch.setattr(get_settings(), "gemini_api_key", SecretStr("k"))
        body = (await sk_client.get("/api/v1/chat/voice/config", headers=auth("dev"))).json()
        assert body["enabled"] is True
        assert body["max_session_seconds"] == 1800
        assert body["idle_timeout_seconds"] == 300

    async def test_no_key_says_disabled(self, sk_client, auth, monkeypatch) -> None:
        monkeypatch.setattr(get_settings(), "gemini_api_key", SecretStr(""))
        body = (await sk_client.get("/api/v1/chat/voice/config", headers=auth("dev"))).json()
        assert body["enabled"] is False

    async def test_signing_in_is_required(self, sk_client) -> None:
        response = await sk_client.get("/api/v1/chat/voice/config")
        assert response.status_code in (401, 403)


class TestSession:
    async def test_a_new_chat_gets_a_token(self, sk_client, auth, minted) -> None:
        response = await sk_client.post(
            "/api/v1/chat/voice/session", json={}, headers=auth("dev")
        )
        assert response.status_code == 200
        assert response.json()["token"] == "auth_tokens/abc"
        assert "websocket_url" in response.json()

    async def test_the_chat_so_far_goes_into_the_instruction(
        self, sk_client, auth, sk_people, sk_session, minted
    ) -> None:
        conversation = await make_conversation(sk_session, sk_people["dev"])
        sk_session.add(
            Message(conversation_id=conversation.id, role="user", content="Total is 20.80")
        )
        await sk_session.commit()

        response = await sk_client.post(
            "/api/v1/chat/voice/session",
            json={"conversation_id": conversation.id},
            headers=auth("dev"),
        )
        assert response.status_code == 200
        assert "Total is 20.80" in minted[0]

    async def test_a_reconnect_passes_its_resume_handle(self, sk_client, auth, minted) -> None:
        response = await sk_client.post(
            "/api/v1/chat/voice/session", json={"resume_handle": "h-1"}, headers=auth("dev")
        )
        assert response.status_code == 200
        assert handles == ["h-1"]

    async def test_the_search_tool_comes_with_web_search(
        self, sk_client, auth, minted, monkeypatch
    ) -> None:
        for available in (True, False):
            monkeypatch.setattr(
                "app.api.v1.voice.router.web_search_available", lambda on=available: on
            )
            await sk_client.post("/api/v1/chat/voice/session", json={}, headers=auth("dev"))
        assert tools_seen[0] == [TOOL_DECLARATION]
        assert "call web_search" in minted[0]
        assert tools_seen[1] is None
        assert "web_search" not in minted[1]

    async def test_someone_elses_chat_is_not_found(
        self, sk_client, auth, sk_people, sk_session, minted
    ) -> None:
        conversation = await make_conversation(sk_session, sk_people["dev2"])
        response = await sk_client.post(
            "/api/v1/chat/voice/session",
            json={"conversation_id": conversation.id},
            headers=auth("dev"),
        )
        assert response.status_code == 404
        assert minted == []

    async def test_a_missing_key_is_a_clear_503(self, sk_client, auth, monkeypatch) -> None:
        monkeypatch.setattr(get_settings(), "gemini_api_key", SecretStr(""))
        response = await sk_client.post(
            "/api/v1/chat/voice/session", json={}, headers=auth("dev")
        )
        assert response.status_code == 503
        assert "voice_not_configured" in response.text


class TestSearch:
    async def test_the_model_query_is_searched(self, sk_client, auth, monkeypatch) -> None:
        asked: list[str] = []

        async def fake(query: str) -> dict:
            asked.append(query)
            return {"found": True, "note": "n", "results": []}

        monkeypatch.setattr("app.api.v1.voice.router.voice_search", fake)
        response = await sk_client.post(
            "/api/v1/chat/voice/search", json={"query": "current CM of Tamil Nadu"},
            headers=auth("dev"),
        )
        assert response.status_code == 200
        assert asked == ["current CM of Tamil Nadu"]

    async def test_signing_in_is_required(self, sk_client) -> None:
        response = await sk_client.post("/api/v1/chat/voice/search", json={"query": "x"})
        assert response.status_code in (401, 403)


class TestTurns:
    async def test_the_first_turn_creates_and_titles_the_chat(
        self, sk_client, auth, sk_people, sk_session, memory
    ) -> None:
        conversation_id = str(uuid.uuid4())
        response = await sk_client.post(
            "/api/v1/chat/voice/turns",
            json={
                "conversation_id": conversation_id,
                "turns": [turn("user", "What is a petty cash claim?"), turn("assistant", "It is…")],
            },
            headers=auth("dev"),
        )
        assert response.status_code == 200
        conversation = await sk_session.get(Conversation, conversation_id)
        assert conversation.user_id == sk_people["dev"].id
        assert conversation.title == "What is a petty cash claim?"

        rows = (
            await sk_session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at)
            )
        ).scalars().all()
        assert [(m.role, m.agent_used) for m in rows] == [
            ("user", "voice_agent"),
            ("assistant", "voice_agent"),
        ]

    async def test_sending_a_turn_twice_saves_it_once(
        self, sk_client, auth, sk_session, memory
    ) -> None:
        conversation_id = str(uuid.uuid4())
        payload = {"conversation_id": conversation_id, "turns": [turn("user", "Once only")]}
        for _ in range(2):
            response = await sk_client.post(
                "/api/v1/chat/voice/turns", json=payload, headers=auth("dev")
            )
            assert response.status_code == 200
        rows = (
            await sk_session.execute(
                select(Message).where(Message.conversation_id == conversation_id)
            )
        ).scalars().all()
        assert len(rows) == 1
        assert len(memory) == 1, "a retry does not double the session memory either"

    async def test_turns_reach_session_memory(self, sk_client, auth, memory, sk_people) -> None:
        conversation_id = str(uuid.uuid4())
        await sk_client.post(
            "/api/v1/chat/voice/turns",
            json={"conversation_id": conversation_id, "turns": [turn("user", "Remember me")]},
            headers=auth("dev"),
        )
        assert memory == [(sk_people["dev"].id, conversation_id, "user", "Remember me")]

    async def test_someone_elses_chat_is_not_found(
        self, sk_client, auth, sk_people, sk_session, memory
    ) -> None:
        conversation = await make_conversation(sk_session, sk_people["dev2"])
        response = await sk_client.post(
            "/api/v1/chat/voice/turns",
            json={"conversation_id": conversation.id, "turns": [turn("user", "Sneak in")]},
            headers=auth("dev"),
        )
        assert response.status_code == 404

    async def test_a_turn_cannot_overwrite_or_join_another_chats_message(
        self, sk_client, auth, sk_people, sk_session, memory
    ) -> None:
        other = await make_conversation(sk_session, sk_people["dev2"])
        existing = Message(conversation_id=other.id, role="user", content="Private")
        sk_session.add(existing)
        await sk_session.commit()

        mine = str(uuid.uuid4())
        response = await sk_client.post(
            "/api/v1/chat/voice/turns",
            json={"conversation_id": mine, "turns": [turn("user", "Hijack", existing.id)]},
            headers=auth("dev"),
        )
        assert response.status_code == 200
        await sk_session.refresh(existing)
        assert existing.content == "Private"
        assert existing.conversation_id == other.id

    async def test_session_memory_being_down_does_not_lose_the_save(
        self, sk_client, auth, sk_session, monkeypatch
    ) -> None:
        async def down(*args, **kwargs):  # noqa: ANN002, ANN003
            raise ConnectionError("redis is down")

        monkeypatch.setattr("app.api.v1.voice.router.push_session_message", down)
        conversation_id = str(uuid.uuid4())
        response = await sk_client.post(
            "/api/v1/chat/voice/turns",
            json={"conversation_id": conversation_id, "turns": [turn("user", "Keep me")]},
            headers=auth("dev"),
        )
        assert response.status_code == 200
        assert await sk_session.get(Conversation, conversation_id) is not None

    async def test_blank_turns_leave_nothing_behind(
        self, sk_client, auth, sk_session, memory
    ) -> None:
        conversation_id = str(uuid.uuid4())
        response = await sk_client.post(
            "/api/v1/chat/voice/turns",
            json={"conversation_id": conversation_id, "turns": [turn("user", "   ")]},
            headers=auth("dev"),
        )
        assert response.status_code == 200
        assert await sk_session.get(Conversation, conversation_id) is None
