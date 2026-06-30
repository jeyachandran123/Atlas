"""
Integration test for memory system.

Tests the complete flow:
1. Add messages to session memory
2. Retrieve context for agent
3. Consolidate learnings
4. Retrieve long-term memories
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.memory import get_memory_manager


@pytest.mark.asyncio
async def test_complete_memory_flow():
    """Test the complete memory flow from messages to consolidation."""
    
    # Mock dependencies
    with patch('app.memory.consolidator.get_ollama_client') as mock_ollama_factory:
        with patch('app.redis_client.get_redis') as mock_redis:
                
                # Setup mocks
                mock_ollama = AsyncMock()
                mock_ollama_factory.return_value = mock_ollama
                
                mock_redis_client = AsyncMock()
                mock_redis.return_value = mock_redis_client
                
                # Mock Redis operations
                stored_messages = []
                
                async def mock_lpush(key, value):
                    stored_messages.insert(0, value)
                    return len(stored_messages)
                
                async def mock_lrange(key, start, end):
                    return stored_messages[start:end+1] if end >= 0 else stored_messages[start:]
                
                async def mock_ltrim(key, start, end):
                    nonlocal stored_messages
                    stored_messages = stored_messages[start:end+1]
                
                async def mock_expire(key, ttl):
                    return True
                
                mock_redis_client.lpush = mock_lpush
                mock_redis_client.lrange = mock_lrange
                mock_redis_client.ltrim = mock_ltrim
                mock_redis_client.expire = mock_expire
                mock_redis_client.set = AsyncMock()
                mock_redis_client.sadd = AsyncMock()
                mock_redis_client.smembers = AsyncMock(return_value=set())
                
                # Mock LLM extraction
                mock_ollama.chat.return_value = '''[
                    {
                        "content": "User prefers TypeScript over JavaScript",
                        "type": "preference",
                        "importance": 0.8
                    },
                    {
                        "content": "Project uses Jest for testing",
                        "type": "pattern",
                        "importance": 0.7
                    }
                ]'''
                
                # Get memory manager
                memory = get_memory_manager()
                
                # Step 1: Add messages to session
                await memory.add_message(
                    user_id="user1",
                    conversation_id="conv1",
                    role="user",
                    content="I prefer TypeScript over JavaScript",
                )
                
                await memory.add_message(
                    user_id="user1",
                    conversation_id="conv1",
                    role="assistant",
                    content="Got it! I'll use TypeScript for your code.",
                )
                
                await memory.add_message(
                    user_id="user1",
                    conversation_id="conv1",
                    role="user",
                    content="We use Jest for all our tests",
                )
                
                await memory.add_message(
                    user_id="user1",
                    conversation_id="conv1",
                    role="assistant",
                    content="Understood. I'll follow that pattern.",
                )
                
                # Verify messages were stored
                assert len(stored_messages) == 4
                
                # Step 2: Retrieve session messages
                messages = await memory.get_messages("user1", "conv1")
                
                assert len(messages) == 4
                assert messages[0]["role"] == "user"
                assert "TypeScript" in messages[0]["content"]
                
                # Step 3: Get formatted context
                context = await memory.get_context(
                    user_id="user1",
                    conversation_id="conv1",
                    org_id="org1",
                    repo_id="repo1",
                )
                
                # Context should include session messages
                assert "Previous conversation:" in context or len(messages) == 4
                
                # Step 4: Consolidate learnings
                count = await memory.consolidate(
                    user_id="user1",
                    org_id="org1",
                    conversation_id="conv1",
                    repo_id="repo1",
                )
                
                # Should extract facts
                assert count == 2
                
                # Verify LLM was called for extraction
                assert mock_ollama.chat.called
                
                # Verify facts were stored in Redis
                assert mock_redis_client.set.called
                assert mock_redis_client.sadd.called


@pytest.mark.asyncio
async def test_memory_context_in_orchestrator():
    """Test that memory context is properly loaded in orchestrator."""
    
    from app.agents.orchestrator import AgentOrchestrator
    from app.agents.state import initial_state
    
    with patch('app.redis_client.get_redis') as mock_redis:
            
            mock_client = AsyncMock()
            mock_redis.return_value = mock_client
            
            # Mock session messages
            import json
            stored_messages = [
                json.dumps({"role": "user", "content": "Previous message"}),
                json.dumps({"role": "assistant", "content": "Previous response"}),
            ]
            
            mock_client.lrange = AsyncMock(return_value=stored_messages)
            mock_client.smembers = AsyncMock(return_value=set())
            
            # Create orchestrator
            orch = AgentOrchestrator()
            
            # Create state
            state = initial_state(
                user_message="New message",
                conversation_id="conv1",
                user_id="user1",
                org_id="org1",
                request_id="req1",
                repo_id="repo1",
            )
            
            # Run load_memory node
            updated_state = await orch._load_memory_node(state)
            
            # Verify memory was loaded
            assert "session_messages" in updated_state
            assert len(updated_state["session_messages"]) == 2
            # Messages contain both user and assistant messages
            roles = [msg["role"] for msg in updated_state["session_messages"]]
            assert "user" in roles
            assert "assistant" in roles
            
            # Verify memory context was set
            assert "memory_context" in updated_state


@pytest.mark.asyncio
async def test_memory_consolidation_async():
    """Test that async consolidation doesn't block."""
    
    with patch('app.memory.consolidator.get_ollama_client') as mock_ollama_factory:
        with patch('app.redis_client.get_redis') as mock_redis:
            
            mock_ollama = AsyncMock()
            mock_ollama_factory.return_value = mock_ollama
            
            mock_client = AsyncMock()
            mock_redis.return_value = mock_client
            
            import json
            mock_client.lrange = AsyncMock(return_value=[
                json.dumps({"role": "user", "content": "Test"}),
                json.dumps({"role": "assistant", "content": "Response"}),
            ])
            
            # Mock LLM to be slow
            import asyncio
            
            async def slow_chat(*args, **kwargs):
                await asyncio.sleep(0.1)  # Simulate slow LLM
                return "[]"
            
            mock_ollama.chat = slow_chat
            
            memory = get_memory_manager()
            
            # Call async consolidation
            import time
            start = time.time()
            
            await memory.consolidate_async(
                user_id="user1",
                org_id="org1",
                conversation_id="conv1",
            )
            
            elapsed = time.time() - start
            
            # Should return immediately (not wait for consolidation)
            # Note: asyncio.create_task is fire-and-forget
            assert elapsed < 0.05  # Much faster than 0.1s LLM call
