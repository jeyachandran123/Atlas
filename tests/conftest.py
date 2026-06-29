"""
Shared test fixtures.

Provides:
  - async test client (FastAPI TestClient)
  - in-memory SQLite database for isolation
  - fake Redis (fakeredis)
  - in-memory ChromaDB
  - mocked Ollama client
  - pre-created test user + organisation
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import create_access_token, hash_password
from app.database import Base, get_db
from app.db.models import Organization, User


# ─────────────────────────────────────────────────────────────────────────────
# DATABASE FIXTURE (SQLite in-memory)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """In-memory SQLite engine — isolated per test session."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional test session that rolls back after each test."""
    factory = async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with factory() as session:
        yield session
        await session.rollback()


# ─────────────────────────────────────────────────────────────────────────────
# REDIS FIXTURE (fakeredis)
# ─────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def fake_redis():
    """In-memory Redis replacement using fakeredis."""
    import fakeredis.aioredis as fake_redis_module

    r = fake_redis_module.FakeRedis(decode_responses=True)
    yield r
    await r.flushall()
    await r.aclose()


# ─────────────────────────────────────────────────────────────────────────────
# VECTOR STORE FIXTURE (in-memory ChromaDB)
# ─────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def vector_store():
    """In-memory ChromaDB for tests."""
    from app.vector_store.chroma_client import get_test_store
    store = await get_test_store()
    yield store


# ─────────────────────────────────────────────────────────────────────────────
# OLLAMA MOCK
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_ollama():
    """Mock Ollama client that returns canned responses without making HTTP calls."""
    mock = MagicMock()
    mock.chat = AsyncMock(return_value="MOCKED_AI_RESPONSE")
    mock.embed = AsyncMock(return_value=[[0.1] * 768])
    mock.health_check = AsyncMock(return_value=(True, 5))
    mock.list_models = AsyncMock(return_value=["qwen2.5-coder:7b"])

    async def _stream(*args, **kwargs):
        for chunk in ["MOCKED ", "STREAM ", "RESPONSE"]:
            yield chunk

    mock.chat_stream = _stream
    return mock


# ─────────────────────────────────────────────────────────────────────────────
# TEST DATA: org + user
# ─────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_org(db_session: AsyncSession) -> Organization:
    """Create a test organisation."""
    org = Organization(
        name="Test Org",
        slug="test-org",
        plan="free",
    )
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession, test_org: Organization) -> User:
    """Create a test developer user."""
    user = User(
        org_id=test_org.id,
        email="dev@test.com",
        hashed_password=hash_password("password123"),
        full_name="Test Developer",
        role="developer",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession, test_org: Organization) -> User:
    """Create a test admin user."""
    user = User(
        org_id=test_org.id,
        email="admin@test.com",
        hashed_password=hash_password("password123"),
        full_name="Test Admin",
        role="admin",
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.fixture
def developer_token(test_user: User) -> str:
    """JWT access token for the test developer."""
    return create_access_token(test_user.id, test_user.org_id, "developer")


@pytest.fixture
def admin_token(admin_user: User) -> str:
    """JWT access token for the test admin."""
    return create_access_token(admin_user.id, admin_user.org_id, "admin")


# ─────────────────────────────────────────────────────────────────────────────
# TEST CLIENT
# ─────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession,
    mock_ollama,
    vector_store,
) -> AsyncGenerator[AsyncClient, None]:
    """
    Async test client with all dependencies overridden:
    - DB → in-memory SQLite
    - Ollama → mock
    - ChromaDB → in-memory
    """
    from app.main import create_app
    from app.agents.orchestrator import AgentOrchestrator
    from app.retrieval.context_builder import ContextBuilder
    from app.retrieval.retriever import CodeRetriever

    app = create_app()

    # Override DB dependency
    async def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db

    # Set up orchestrator with mocked Ollama
    from app.agents.coding_agent import CodingAgent
    coding_agent = CodingAgent(ollama=mock_ollama)
    retriever = CodeRetriever(vector_store=vector_store, ollama_client=mock_ollama)
    orchestrator = AgentOrchestrator(
        vector_store=vector_store,
        coding_agent=coding_agent,
        retriever=retriever,
    )
    app.state.orchestrator = orchestrator

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
