"""Fixtures for the Document Intelligence Platform's conversation layer."""

from __future__ import annotations

import asyncio

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "filterwarnings",
        "ignore:The event_loop fixture provided by pytest-asyncio has been "
        "redefined:DeprecationWarning",
    )


@pytest.fixture
def event_loop():
    """Function-scoped loop, shadowing the Atlas root conftest's session-scoped one.

    The same workaround ``tests/document_vlm`` documents: these tests have no
    database, no FastAPI lifespan and no session-scoped async state, and
    inheriting a session loop breaks fixture introspection under
    pytest-asyncio 0.24.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
