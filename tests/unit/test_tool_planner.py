"""
Unit tests for tool planner.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.tool_planner import ToolPlanner
from app.agents.state import initial_state
from app.shared.schemas import ToolCall


@pytest.fixture
def mock_ollama():
    """Mock Ollama client for testing."""
    mock = AsyncMock()
    return mock


@pytest.fixture
def tool_planner(mock_ollama):
    """Create a tool planner with mocked Ollama."""
    planner = ToolPlanner(ollama=mock_ollama)
    return planner


@pytest.mark.asyncio
async def test_plan_no_tools_needed(tool_planner, mock_ollama):
    """Test when LLM decides no tools are needed."""
    mock_ollama.chat.return_value = "[]"
    
    state = initial_state(
        user_message="What is Python?",
        conversation_id="conv1",
        user_id="user1",
        org_id="org1",
        request_id="req1",
    )
    
    tool_calls = await tool_planner.plan(state)
    
    assert tool_calls == []
    assert mock_ollama.chat.called


@pytest.mark.asyncio
async def test_plan_single_tool(tool_planner, mock_ollama):
    """Test when LLM plans a single tool call."""
    mock_ollama.chat.return_value = '''
    [{"tool": "search_code", "args": {"query": "authentication"}, "rationale": "Find auth code"}]
    '''
    
    state = initial_state(
        user_message="Find authentication code",
        conversation_id="conv1",
        user_id="user1",
        org_id="org1",
        request_id="req1",
        repo_id="repo1",
    )
    
    tool_calls = await tool_planner.plan(state)
    
    assert len(tool_calls) == 1
    assert tool_calls[0].tool_name == "search_code"
    assert tool_calls[0].args["query"] == "authentication"
    assert tool_calls[0].rationale == "Find auth code"


@pytest.mark.asyncio
async def test_plan_multiple_tools(tool_planner, mock_ollama):
    """Test when LLM plans multiple tool calls."""
    mock_ollama.chat.return_value = '''
    [
        {"tool": "read_file", "args": {"file_path": "app/main.py"}, "rationale": "Read main file"},
        {"tool": "search_code", "args": {"query": "database connection"}, "rationale": "Find DB code"}
    ]
    '''
    
    state = initial_state(
        user_message="Show me main.py and find database code",
        conversation_id="conv1",
        user_id="user1",
        org_id="org1",
        request_id="req1",
        repo_id="repo1",
    )
    
    tool_calls = await tool_planner.plan(state)
    
    assert len(tool_calls) == 2
    assert tool_calls[0].tool_name == "read_file"
    assert tool_calls[1].tool_name == "search_code"


@pytest.mark.asyncio
async def test_plan_with_markdown_code_block(tool_planner, mock_ollama):
    """Test parsing when LLM wraps response in markdown code blocks."""
    mock_ollama.chat.return_value = '''```json
    [{"tool": "git_diff", "args": {}, "rationale": "Show changes"}]
    ```'''
    
    state = initial_state(
        user_message="What changed?",
        conversation_id="conv1",
        user_id="user1",
        org_id="org1",
        request_id="req1",
        repo_id="repo1",
    )
    
    tool_calls = await tool_planner.plan(state)
    
    assert len(tool_calls) == 1
    assert tool_calls[0].tool_name == "git_diff"


@pytest.mark.asyncio
async def test_plan_max_steps_reached(tool_planner, mock_ollama):
    """Test that planning is skipped when max steps reached."""
    state = initial_state(
        user_message="Do something",
        conversation_id="conv1",
        user_id="user1",
        org_id="org1",
        request_id="req1",
        repo_id="repo1",
    )
    state["current_step"] = 5
    state["max_steps"] = 5
    
    tool_calls = await tool_planner.plan(state)
    
    assert tool_calls == []
    assert not mock_ollama.chat.called


@pytest.mark.asyncio
async def test_plan_invalid_json_returns_empty(tool_planner, mock_ollama):
    """Test that invalid JSON returns empty list instead of crashing."""
    mock_ollama.chat.return_value = "This is not valid JSON"
    
    state = initial_state(
        user_message="Find something",
        conversation_id="conv1",
        user_id="user1",
        org_id="org1",
        request_id="req1",
        repo_id="repo1",
    )
    
    tool_calls = await tool_planner.plan(state)
    
    assert tool_calls == []


@pytest.mark.asyncio
async def test_plan_ollama_error_returns_empty(tool_planner, mock_ollama):
    """Test that Ollama errors don't crash the planner."""
    mock_ollama.chat.side_effect = Exception("Ollama unavailable")
    
    state = initial_state(
        user_message="Find something",
        conversation_id="conv1",
        user_id="user1",
        org_id="org1",
        request_id="req1",
        repo_id="repo1",
    )
    
    tool_calls = await tool_planner.plan(state)
    
    assert tool_calls == []
