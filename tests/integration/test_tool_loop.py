"""
Integration test for tool-use loop.

Tests the complete flow: user request → tool planning → tool execution → agent response
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.orchestrator import AgentOrchestrator
from app.agents.state import initial_state


@pytest.fixture
def mock_vector_store():
    """Mock vector store."""
    vs = AsyncMock()
    vs.search = AsyncMock(return_value=[])
    return vs


@pytest.fixture
def mock_ollama():
    """Mock Ollama client."""
    ollama = AsyncMock()
    return ollama


@pytest.fixture
def orchestrator(mock_vector_store, mock_ollama):
    """Create orchestrator with mocked dependencies."""
    with patch('app.agents.orchestrator.get_ollama_client', return_value=mock_ollama):
        with patch('app.agents.tool_planner.get_ollama_client', return_value=mock_ollama):
            orch = AgentOrchestrator(vector_store=mock_vector_store)
            return orch


@pytest.mark.asyncio
async def test_simple_request_no_tools(orchestrator, mock_ollama):
    """Test simple request that doesn't need tools."""
    # Mock tool planner to return no tools
    mock_ollama.chat.side_effect = [
        "[]",  # Tool planning returns empty
        "Python is a programming language."  # Agent response
    ]
    
    state = initial_state(
        user_message="What is Python?",
        conversation_id="conv1",
        user_id="user1",
        org_id="org1",
        request_id="req1",
    )
    
    result = await orchestrator.run(state)
    
    assert result["final_response"] == "Python is a programming language."
    assert result["current_step"] == 0  # No tools executed
    assert len(result["tool_results"]) == 0


@pytest.mark.asyncio
async def test_request_with_single_tool(orchestrator, mock_ollama):
    """Test request that triggers a single tool call."""
    # Mock responses
    mock_ollama.chat.side_effect = [
        '[{"tool": "read_file", "args": {"file_path": "README.md"}, "rationale": "Read file"}]',  # Tool planning
        "Here's what I found in README.md: ...",  # Agent response
        "[]",  # No more tools needed (should_continue)
    ]
    
    # Mock file read tool
    with patch('app.agents.tools.tool_impls.OldFileTool') as mock_file_tool:
        mock_instance = AsyncMock()
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output = "# Project README\nThis is a test project."
        mock_result.error = None
        mock_instance._execute = AsyncMock(return_value=mock_result)
        mock_file_tool.return_value = mock_instance
        
        # Mock database call for repo path
        with patch('app.agents.orchestrator.get_db_session') as mock_db:
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock()
            mock_db.return_value = mock_session
            
            with patch('app.agents.orchestrator.RepositoryRepo') as mock_repo_repo:
                mock_repo_instance = MagicMock()
                mock_repo = MagicMock()
                mock_repo.local_path = "/test/repo"
                mock_repo_instance.get_by_id = AsyncMock(return_value=mock_repo)
                mock_repo_repo.return_value = mock_repo_instance
                
                state = initial_state(
                    user_message="Show me the README",
                    conversation_id="conv1",
                    user_id="user1",
                    org_id="org1",
                    request_id="req1",
                    repo_id="repo1",
                )
                
                result = await orchestrator.run(state)
                
                assert result["current_step"] == 1  # One iteration
                assert len(result["tool_results"]) == 1
                assert result["tool_results"][0].tool_name == "read_file"
                assert result["tool_results"][0].success is True
                assert "Here's what I found" in result["final_response"]


@pytest.mark.asyncio
async def test_tool_loop_max_steps(orchestrator, mock_ollama):
    """Test that tool loop respects max_steps limit."""
    # Mock tool planner to always return tools (simulating infinite loop)
    mock_ollama.chat.return_value = '[{"tool": "search_code", "args": {"query": "test"}}]'
    
    # Mock search tool
    with patch('app.agents.tools.tool_impls.get_chroma_store') as mock_store:
        mock_store.return_value = AsyncMock()
        
        with patch('app.agents.tools.tool_impls.CodeRetriever') as mock_retriever:
            mock_ret_instance = AsyncMock()
            mock_ret_instance.retrieve = AsyncMock(return_value=[])
            mock_retriever.return_value = mock_ret_instance
            
            state = initial_state(
                user_message="Find something",
                conversation_id="conv1",
                user_id="user1",
                org_id="org1",
                request_id="req1",
                repo_id="repo1",
            )
            state["max_steps"] = 3  # Set low limit for test
            
            result = await orchestrator.run(state)
            
            # Should stop at max_steps
            assert result["current_step"] >= 3
            assert result["current_step"] <= 5  # Default max is 5


@pytest.mark.asyncio
async def test_tool_execution_error_doesnt_crash(orchestrator, mock_ollama):
    """Test that tool execution errors are handled gracefully."""
    mock_ollama.chat.side_effect = [
        '[{"tool": "read_file", "args": {"file_path": "nonexistent.txt"}}]',  # Tool planning
        "I couldn't read the file, but here's what I know...",  # Agent response
        "[]",  # No more tools
    ]
    
    # Mock file tool to raise error
    with patch('app.agents.tools.tool_impls.OldFileTool') as mock_file_tool:
        mock_instance = AsyncMock()
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "File not found: nonexistent.txt"
        mock_result.output = None
        mock_instance._execute = AsyncMock(return_value=mock_result)
        mock_file_tool.return_value = mock_instance
        
        with patch('app.agents.orchestrator.get_db_session'):
            with patch('app.agents.orchestrator.RepositoryRepo'):
                state = initial_state(
                    user_message="Read nonexistent file",
                    conversation_id="conv1",
                    user_id="user1",
                    org_id="org1",
                    request_id="req1",
                    repo_id="repo1",
                )
                
                result = await orchestrator.run(state)
                
                # Should complete despite tool failure
                assert result["final_response"]
                assert len(result["tool_results"]) == 1
                assert result["tool_results"][0].success is False
                assert result["error"] is None  # Agent handles the error gracefully


@pytest.mark.asyncio
async def test_intent_routing_with_tools(orchestrator, mock_ollama):
    """Test that different intents still work with tool loop."""
    mock_ollama.chat.side_effect = [
        "[]",  # No tools for simple question
        "Code is organized into modules..."  # Agent explanation
    ]
    
    state = initial_state(
        user_message="Explain how the code is organized",
        conversation_id="conv1",
        user_id="user1",
        org_id="org1",
        request_id="req1",
        repo_id="repo1",
    )
    
    result = await orchestrator.run(state)
    
    assert result["intent"] == "explain"
    assert result["final_response"]
