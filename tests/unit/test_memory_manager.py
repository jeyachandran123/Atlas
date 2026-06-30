"""
Unit tests for memory manager.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.memory.manager import MemoryManager


@pytest.fixture
def mock_session():
    """Create a mock session memory."""
    session = AsyncMock()
    session.add_message = AsyncMock()
    session.get_messages = AsyncMock(return_value=[])
    session.get_formatted_context = AsyncMock(return_value="")
    session.clear = AsyncMock()
    return session


@pytest.fixture
def mock_ltm():
    """Create a mock long-term memory."""
    ltm = AsyncMock()
    ltm.get_formatted_context = AsyncMock(return_value="")
    ltm.delete = AsyncMock(return_value=True)
    return ltm


@pytest.fixture
def mock_consolidator():
    """Create a mock consolidator."""
    consolidator = AsyncMock()
    consolidator.consolidate = AsyncMock(return_value=2)
    consolidator.consolidate_async = AsyncMock()
    return consolidator


@pytest.fixture
def memory_manager(mock_session, mock_ltm, mock_consolidator):
    """Create a memory manager with mocked dependencies."""
    return MemoryManager(
        session=mock_session,
        long_term=mock_ltm,
        consolidator=mock_consolidator,
    )


@pytest.mark.asyncio
async def test_add_message(memory_manager, mock_session):
    """Test adding a message."""
    await memory_manager.add_message("user1", "conv1", "user", "Hello")
    
    mock_session.add_message.assert_called_once_with("user1", "conv1", "user", "Hello")


@pytest.mark.asyncio
async def test_get_messages(memory_manager, mock_session):
    """Test getting messages."""
    mock_session.get_messages.return_value = [
        {"role": "user", "content": "Hello"},
    ]
    
    messages = await memory_manager.get_messages("user1", "conv1")
    
    assert len(messages) == 1
    mock_session.get_messages.assert_called_once_with("user1", "conv1", None)


@pytest.mark.asyncio
async def test_get_context_with_both_memories(memory_manager, mock_session, mock_ltm):
    """Test getting context with both session and long-term memory."""
    mock_ltm.get_formatted_context.return_value = "Long-term: User prefers TypeScript"
    mock_session.get_formatted_context.return_value = "Session: Previous conversation"
    
    context = await memory_manager.get_context(
        user_id="user1",
        conversation_id="conv1",
        org_id="org1",
        repo_id="repo1",
    )
    
    assert "Long-term: User prefers TypeScript" in context
    assert "Session: Previous conversation" in context
    mock_ltm.get_formatted_context.assert_called_once()
    mock_session.get_formatted_context.assert_called_once()


@pytest.mark.asyncio
async def test_get_context_handles_ltm_error(memory_manager, mock_session, mock_ltm):
    """Test that get_context handles long-term memory errors gracefully."""
    mock_ltm.get_formatted_context.side_effect = Exception("Redis error")
    mock_session.get_formatted_context.return_value = "Session: Previous conversation"
    
    # Should not raise, should return session context only
    context = await memory_manager.get_context(
        user_id="user1",
        conversation_id="conv1",
        org_id="org1",
    )
    
    assert "Session: Previous conversation" in context


@pytest.mark.asyncio
async def test_get_context_handles_session_error(memory_manager, mock_session, mock_ltm):
    """Test that get_context handles session memory errors gracefully."""
    mock_ltm.get_formatted_context.return_value = "Long-term: User prefers TypeScript"
    mock_session.get_formatted_context.side_effect = Exception("Redis error")
    
    # Should not raise, should return LTM context only
    context = await memory_manager.get_context(
        user_id="user1",
        conversation_id="conv1",
        org_id="org1",
    )
    
    assert "Long-term: User prefers TypeScript" in context


@pytest.mark.asyncio
async def test_get_context_empty(memory_manager, mock_session, mock_ltm):
    """Test getting context when no memories exist."""
    mock_ltm.get_formatted_context.return_value = ""
    mock_session.get_formatted_context.return_value = ""
    
    context = await memory_manager.get_context(
        user_id="user1",
        conversation_id="conv1",
        org_id="org1",
    )
    
    assert context == ""


@pytest.mark.asyncio
async def test_consolidate(memory_manager, mock_session, mock_consolidator):
    """Test memory consolidation."""
    mock_session.get_messages.return_value = [
        {"role": "user", "content": "I prefer TypeScript"},
        {"role": "assistant", "content": "Got it!"},
    ]
    
    count = await memory_manager.consolidate(
        user_id="user1",
        org_id="org1",
        conversation_id="conv1",
        repo_id="repo1",
    )
    
    assert count == 2
    mock_consolidator.consolidate.assert_called_once()


@pytest.mark.asyncio
async def test_consolidate_async(memory_manager, mock_session, mock_consolidator):
    """Test async memory consolidation."""
    mock_session.get_messages.return_value = [
        {"role": "user", "content": "Test"},
    ]
    
    await memory_manager.consolidate_async(
        user_id="user1",
        org_id="org1",
        conversation_id="conv1",
    )
    
    mock_consolidator.consolidate_async.assert_called_once()


@pytest.mark.asyncio
async def test_clear_session(memory_manager, mock_session):
    """Test clearing session memory."""
    await memory_manager.clear_session("user1", "conv1")
    
    mock_session.clear.assert_called_once_with("user1", "conv1")


@pytest.mark.asyncio
async def test_delete_memory(memory_manager, mock_ltm):
    """Test deleting a memory."""
    result = await memory_manager.delete_memory("user1", "mem1")
    
    assert result is True
    mock_ltm.delete.assert_called_once_with("user1", "mem1")


@pytest.mark.asyncio
async def test_get_context_with_limits(memory_manager, mock_session, mock_ltm):
    """Test getting context with custom limits."""
    await memory_manager.get_context(
        user_id="user1",
        conversation_id="conv1",
        org_id="org1",
        session_limit=5,
        ltm_limit=2,
    )
    
    # Check that limits are passed correctly
    mock_session.get_formatted_context.assert_called_once()
    call_kwargs = mock_session.get_formatted_context.call_args[1]
    assert call_kwargs["limit"] == 5
    
    mock_ltm.get_formatted_context.assert_called_once()
    call_kwargs = mock_ltm.get_formatted_context.call_args[1]
    assert call_kwargs["limit"] == 2
