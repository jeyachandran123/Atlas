"""
Unit tests for long-term memory.
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.memory.long_term import LongTermMemory, MemoryEntry


@pytest.fixture
def ltm():
    """Create a LongTermMemory instance."""
    return LongTermMemory()


@pytest.fixture
def sample_entry():
    """Create a sample memory entry."""
    return MemoryEntry(
        user_id="user1",
        org_id="org1",
        content="User prefers TypeScript over JavaScript",
        memory_type="preference",
        importance=0.8,
        repo_id="repo1",
        source_conversation_id="conv1",
    )


def test_memory_entry_to_dict(sample_entry):
    """Test converting MemoryEntry to dict."""
    data = sample_entry.to_dict()
    
    assert data["user_id"] == "user1"
    assert data["org_id"] == "org1"
    assert data["content"] == "User prefers TypeScript over JavaScript"
    assert data["memory_type"] == "preference"
    assert data["importance"] == 0.8
    assert data["repo_id"] == "repo1"
    assert "id" in data


def test_memory_entry_from_dict():
    """Test creating MemoryEntry from dict."""
    data = {
        "id": "mem123",
        "user_id": "user1",
        "org_id": "org1",
        "content": "Test memory",
        "memory_type": "fact",
        "importance": 0.7,
        "repo_id": "repo1",
        "source_conversation_id": "conv1",
        "created_at": "2024-01-01T00:00:00+00:00",
        "accessed_count": 5,
        "last_accessed_at": "2024-01-02T00:00:00+00:00",
    }
    
    entry = MemoryEntry.from_dict(data)
    
    assert entry.id == "mem123"
    assert entry.user_id == "user1"
    assert entry.content == "Test memory"
    assert entry.memory_type == "fact"
    assert entry.importance == 0.7
    assert entry.accessed_count == 5


@pytest.mark.asyncio
async def test_store_memory(ltm, sample_entry):
    """Test storing a memory entry."""
    with patch('app.redis_client.get_redis') as mock_redis:
        mock_client = AsyncMock()
        mock_redis.return_value = mock_client
        
        await ltm.store(sample_entry)
        
        # Should store in Redis
        assert mock_client.set.called
        assert mock_client.sadd.called
        assert mock_client.expire.called


@pytest.mark.asyncio
async def test_retrieve_memory_no_filters(ltm):
    """Test retrieving memories without filters."""
    with patch('app.redis_client.get_redis') as mock_redis:
        mock_client = AsyncMock()
        mock_redis.return_value = mock_client
        
        # Mock index
        mock_client.smembers.return_value = {"mem1", "mem2"}
        
        # Mock memory data
        mem1_data = {
            "id": "mem1",
            "user_id": "user1",
            "org_id": "org1",
            "content": "Memory 1",
            "memory_type": "fact",
            "importance": 0.9,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "accessed_count": 0,
        }
        
        mem2_data = {
            "id": "mem2",
            "user_id": "user1",
            "org_id": "org1",
            "content": "Memory 2",
            "memory_type": "preference",
            "importance": 0.7,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "accessed_count": 0,
        }
        
        async def mock_get(key):
            if "mem1" in key:
                return json.dumps(mem1_data)
            elif "mem2" in key:
                return json.dumps(mem2_data)
            return None
        
        mock_client.get.side_effect = mock_get
        
        memories = await ltm.retrieve(user_id="user1", limit=5)
        
        # Should return sorted by importance
        assert len(memories) == 2
        assert memories[0].importance >= memories[1].importance


@pytest.mark.asyncio
async def test_retrieve_memory_with_repo_filter(ltm):
    """Test retrieving memories filtered by repo."""
    with patch('app.redis_client.get_redis') as mock_redis:
        mock_client = AsyncMock()
        mock_redis.return_value = mock_client
        
        mock_client.smembers.return_value = {"mem1"}
        
        mem_data = {
            "id": "mem1",
            "user_id": "user1",
            "org_id": "org1",
            "repo_id": "repo1",
            "content": "Memory 1",
            "memory_type": "fact",
            "importance": 0.9,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "accessed_count": 0,
        }
        
        mock_client.get.return_value = json.dumps(mem_data)
        
        # Should return memory matching repo
        memories = await ltm.retrieve(user_id="user1", repo_id="repo1")
        assert len(memories) == 1
        
        # Should filter out non-matching repo
        memories = await ltm.retrieve(user_id="user1", repo_id="repo2")
        assert len(memories) == 0


@pytest.mark.asyncio
async def test_retrieve_memory_with_type_filter(ltm):
    """Test retrieving memories filtered by type."""
    with patch('app.redis_client.get_redis') as mock_redis:
        mock_client = AsyncMock()
        mock_redis.return_value = mock_client
        
        mock_client.smembers.return_value = {"mem1"}
        
        mem_data = {
            "id": "mem1",
            "user_id": "user1",
            "org_id": "org1",
            "content": "Memory 1",
            "memory_type": "preference",
            "importance": 0.9,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "accessed_count": 0,
        }
        
        mock_client.get.return_value = json.dumps(mem_data)
        
        # Should return memory matching type
        memories = await ltm.retrieve(user_id="user1", memory_type="preference")
        assert len(memories) == 1
        
        # Should filter out non-matching type
        memories = await ltm.retrieve(user_id="user1", memory_type="fact")
        assert len(memories) == 0


@pytest.mark.asyncio
async def test_delete_memory(ltm):
    """Test deleting a memory."""
    with patch('app.redis_client.get_redis') as mock_redis:
        mock_client = AsyncMock()
        mock_redis.return_value = mock_client
        
        mock_client.delete.return_value = 1  # Success
        
        result = await ltm.delete("user1", "mem1")
        
        assert result is True
        mock_client.delete.assert_called_once()
        mock_client.srem.assert_called_once()


@pytest.mark.asyncio
async def test_delete_memory_not_found(ltm):
    """Test deleting a non-existent memory."""
    with patch('app.redis_client.get_redis') as mock_redis:
        mock_client = AsyncMock()
        mock_redis.return_value = mock_client
        
        mock_client.delete.return_value = 0  # Not found
        
        result = await ltm.delete("user1", "mem999")
        
        assert result is False


@pytest.mark.asyncio
async def test_get_formatted_context_empty(ltm):
    """Test formatted context with no memories."""
    with patch('app.redis_client.get_redis') as mock_redis:
        mock_client = AsyncMock()
        mock_redis.return_value = mock_client
        
        mock_client.smembers.return_value = set()
        
        context = await ltm.get_formatted_context("user1")
        
        assert context == ""


@pytest.mark.asyncio
async def test_get_formatted_context_with_memories(ltm):
    """Test formatted context with memories."""
    with patch('app.redis_client.get_redis') as mock_redis:
        mock_client = AsyncMock()
        mock_redis.return_value = mock_client
        
        mock_client.smembers.return_value = {"mem1"}
        
        mem_data = {
            "id": "mem1",
            "user_id": "user1",
            "org_id": "org1",
            "content": "User prefers TypeScript",
            "memory_type": "preference",
            "importance": 0.9,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "accessed_count": 0,
        }
        
        mock_client.get.return_value = json.dumps(mem_data)
        
        context = await ltm.get_formatted_context("user1")
        
        assert "Relevant context from past conversations:" in context
        assert "User prefers TypeScript" in context
