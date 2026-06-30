"""
Unit tests for session memory.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.memory.session import SessionMemory


@pytest.fixture
def session_memory():
    """Create a SessionMemory instance."""
    return SessionMemory(max_messages=5, ttl_seconds=3600)


@pytest.mark.asyncio
async def test_add_message(session_memory):
    """Test adding a message to session memory."""
    with patch('app.memory.session.push_session_message') as mock_push:
        mock_push.return_value = None
        
        await session_memory.add_message(
            user_id="user1",
            conversation_id="conv1",
            role="user",
            content="Hello",
        )
        
        mock_push.assert_called_once_with("user1", "conv1", "user", "Hello")


@pytest.mark.asyncio
async def test_get_messages(session_memory):
    """Test retrieving session messages."""
    with patch('app.memory.session.get_session_messages') as mock_get:
        mock_get.return_value = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        
        messages = await session_memory.get_messages("user1", "conv1")
        
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        mock_get.assert_called_once_with("user1", "conv1")


@pytest.mark.asyncio
async def test_get_messages_with_limit(session_memory):
    """Test retrieving session messages with limit."""
    with patch('app.memory.session.get_session_messages') as mock_get:
        mock_get.return_value = [
            {"role": "user", "content": "Msg1"},
            {"role": "assistant", "content": "Msg2"},
            {"role": "user", "content": "Msg3"},
            {"role": "assistant", "content": "Msg4"},
        ]
        
        messages = await session_memory.get_messages("user1", "conv1", limit=2)
        
        # Should return last 2 messages
        assert len(messages) == 2
        assert messages[0]["content"] == "Msg3"
        assert messages[1]["content"] == "Msg4"


@pytest.mark.asyncio
async def test_clear(session_memory):
    """Test clearing session memory."""
    with patch('app.memory.session.get_redis') as mock_redis:
        mock_client = AsyncMock()
        mock_redis.return_value = mock_client
        
        await session_memory.clear("user1", "conv1")
        
        mock_client.delete.assert_called_once_with("session:user1:conv1")


@pytest.mark.asyncio
async def test_get_formatted_context_empty(session_memory):
    """Test formatted context with no messages."""
    with patch('app.memory.session.get_session_messages') as mock_get:
        mock_get.return_value = []
        
        context = await session_memory.get_formatted_context("user1", "conv1")
        
        assert context == ""


@pytest.mark.asyncio
async def test_get_formatted_context_with_messages(session_memory):
    """Test formatted context with messages."""
    with patch('app.memory.session.get_session_messages') as mock_get:
        mock_get.return_value = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi! How can I help?"},
        ]
        
        context = await session_memory.get_formatted_context("user1", "conv1")
        
        assert "Previous conversation:" in context
        assert "User: Hello" in context
        assert "Assistant: Hi! How can I help?" in context


@pytest.mark.asyncio
async def test_get_formatted_context_truncates_long_messages(session_memory):
    """Test that very long messages are truncated."""
    with patch('app.memory.session.get_session_messages') as mock_get:
        long_message = "x" * 600
        mock_get.return_value = [
            {"role": "user", "content": long_message},
        ]
        
        context = await session_memory.get_formatted_context("user1", "conv1")
        
        # Should truncate to 500 chars + "..."
        assert "..." in context
        assert len(context) < 600
