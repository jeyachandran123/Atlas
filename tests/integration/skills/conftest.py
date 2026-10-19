"""
Fixtures for skills integration tests.

Each test gets its OWN in-memory SQLite database (the skill service commits,
so the shared rollback-based session from tests/conftest.py would leak rows
between tests). Foreign keys are enforced to mirror PostgreSQL cascades.
Redis, Ollama and the vector store are replaced by in-process fakes.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token, hash_password
from app.database import Base, get_db
from app.db.models import Organization, User


@pytest_asyncio.fixture
async def sk_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(dbapi_conn, _record) -> None:  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@lru_cache(maxsize=1)
def _pw_hash() -> str:
    return hash_password("pw")  # bcrypt is slow; hash once per session


async def _user(db: AsyncSession, org: Organization, email: str, role: str) -> User:
    user = User(
        org_id=org.id,
        email=email,
        hashed_password=_pw_hash(),
        full_name=email.split("@")[0],
        role=role,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def sk_people(sk_session: AsyncSession) -> dict[str, Any]:
    org = Organization(name="Org A", slug="org-a", plan="free")
    other_org = Organization(name="Org B", slug="org-b", plan="free")
    sk_session.add_all([org, other_org])
    await sk_session.flush()
    people = {
        "org": org,
        "dev": await _user(sk_session, org, "dev@a.com", "developer"),
        "dev2": await _user(sk_session, org, "dev2@a.com", "developer"),
        "admin": await _user(sk_session, org, "admin@a.com", "admin"),
        "viewer": await _user(sk_session, org, "viewer@a.com", "viewer"),
        "outsider": await _user(sk_session, other_org, "dev@b.com", "developer"),
    }
    await sk_session.commit()
    return people


@pytest.fixture
def auth(sk_people: dict[str, Any]):
    def _headers(who: str) -> dict[str, str]:
        u: User = sk_people[who]
        return {"Authorization": f"Bearer {create_access_token(u.id, u.org_id, u.role)}"}

    return _headers


class FakeLLM:
    """Captures the prompts every streaming call receives."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.chat = AsyncMock(return_value="MOCKED_AI_RESPONSE")
        self.health_check = AsyncMock(return_value=(True, 1))

    async def chat_stream(self, *args: Any, **kwargs: Any):
        self.calls.append(kwargs)
        for chunk in ["MOCKED ", "STREAM ", "RESPONSE"]:
            yield chunk


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM()


@pytest_asyncio.fixture
async def sk_client(
    sk_session: AsyncSession, fake_llm: FakeLLM, monkeypatch
) -> AsyncGenerator[AsyncClient, None]:
    from app.agents.coding_agent import CodingAgent
    from app.agents.orchestrator import AgentOrchestrator, get_orchestrator_dep
    from app.main import create_app
    from app.rate_limit import limiter

    sessions: dict[str, list[dict]] = {}

    async def fake_get_session(user_id: str, conversation_id: str) -> list[dict]:
        return list(sessions.get(f"{user_id}:{conversation_id}", []))

    async def fake_push(
        user_id: str, conversation_id: str, role: str, content: str, *a, **k
    ) -> None:
        sessions.setdefault(f"{user_id}:{conversation_id}", []).append(
            {"role": role, "content": content}
        )

    monkeypatch.setattr("app.api.v1.chat.router.get_session_messages", fake_get_session)
    monkeypatch.setattr("app.api.v1.chat.router.push_session_message", fake_push)
    monkeypatch.setattr(limiter, "enabled", False)

    memory = MagicMock()
    for name in ("get_context", "add_message", "consolidate_async"):
        setattr(memory, name, AsyncMock(return_value=""))
    memory.get_messages = AsyncMock(return_value=[])

    app = create_app()

    async def override_db():
        yield sk_session

    from app.agents.review_agent import ReviewAgent
    from app.intelligence.engine import ConversationIntelligenceEngine

    port = MagicMock()
    port.get_session = AsyncMock(return_value=[])

    orchestrator = AgentOrchestrator(
        vector_store=None,
        coding_agent=CodingAgent(ollama=fake_llm),  # type: ignore[arg-type]
        review_agent=ReviewAgent(ollama=fake_llm),  # type: ignore[arg-type]
        retriever=None,
        memory_manager=memory,
        intelligence_engine=ConversationIntelligenceEngine(memory_port=port),
    )
    app.dependency_overrides[get_db] = override_db
    # /chat/message resolves its orchestrator via this dependency (the global
    # singleton) — override it so no process-wide singletons get built here.
    app.dependency_overrides[get_orchestrator_dep] = lambda: orchestrator
    app.state.orchestrator = orchestrator
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
