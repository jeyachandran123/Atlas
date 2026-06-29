"""
Unit tests for tool executor.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from app.agents.tool_executor import ToolExecutor
from app.shared.schemas import ToolCall, ToolResult
from app.shared.exceptions import ToolExecutionError


@pytest.fixture
def mock_tool():
    """Mock tool for testing."""
    tool = AsyncMock()
    tool.name = "mock_tool"
    tool.execute = AsyncMock(return_value="tool output")
    return tool


@pytest.fixture
def mock_registry(mock_tool):
    """Mock tool registry."""
    registry = MagicMock()
    registry.get = MagicMock(return_value=mock_tool)
    return registry


@pytest.fixture
def tool_executor(mock_registry):
    """Create a tool executor with mocked registry."""
    with patch('app.agents.tool_executor.get_tool_registry', return_value=mock_registry):
        executor = ToolExecutor(timeout_seconds=5)
        return executor


@pytest.mark.asyncio
async def test_execute_successful_tool(tool_executor, mock_registry, mock_tool):
    """Test successful tool execution."""
    tool_call = ToolCall(
        tool_name="mock_tool",
        args={"arg1": "value1"},
        rationale="Test tool"
    )
    context = {"user_id": "user1", "org_id": "org1"}
    
    result = await tool_executor.execute(tool_call, context)
    
    assert result.success is True
    assert result.tool_name == "mock_tool"
    assert result.output == "tool output"
    assert result.error is None
    mock_tool.execute.assert_called_once_with(arg1="value1", context=context)


@pytest.mark.asyncio
async def test_execute_tool_not_found(tool_executor, mock_registry):
    """Test execution when tool doesn't exist."""
    mock_registry.get.return_value = None
    
    tool_call = ToolCall(
        tool_name="nonexistent_tool",
        args={},
        rationale="Test"
    )
    context = {"user_id": "user1"}
    
    result = await tool_executor.execute(tool_call, context)
    
    assert result.success is False
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_execute_tool_timeout(tool_executor, mock_registry, mock_tool):
    """Test that tool execution respects timeout."""
    async def slow_tool(**kwargs):
        await asyncio.sleep(10)  # Longer than timeout
        return "should not reach here"
    
    mock_tool.execute = slow_tool
    
    tool_call = ToolCall(tool_name="mock_tool", args={})
    context = {"user_id": "user1"}
    
    result = await tool_executor.execute(tool_call, context)
    
    assert result.success is False
    assert "timed out" in result.error.lower()


@pytest.mark.asyncio
async def test_execute_tool_raises_exception(tool_executor, mock_tool):
    """Test handling of tool execution errors."""
    mock_tool.execute.side_effect = ToolExecutionError("Tool failed")
    
    tool_call = ToolCall(tool_name="mock_tool", args={})
    context = {"user_id": "user1"}
    
    result = await tool_executor.execute(tool_call, context)
    
    assert result.success is False
    assert "Tool failed" in result.error


@pytest.mark.asyncio
async def test_execute_batch_sequential(tool_executor, mock_tool):
    """Test batch execution runs sequentially."""
    execution_order = []
    
    async def mock_execute(**kwargs):
        execution_order.append(kwargs.get("order"))
        await asyncio.sleep(0.01)
        return f"result_{kwargs.get('order')}"
    
    mock_tool.execute = mock_execute
    
    tool_calls = [
        ToolCall(tool_name="mock_tool", args={"order": 1}),
        ToolCall(tool_name="mock_tool", args={"order": 2}),
        ToolCall(tool_name="mock_tool", args={"order": 3}),
    ]
    context = {"user_id": "user1"}
    
    results = await tool_executor.execute_batch(tool_calls, context)
    
    assert len(results) == 3
    assert execution_order == [1, 2, 3]  # Sequential order preserved
    assert all(r.success for r in results)


@pytest.mark.asyncio
async def test_execute_batch_continues_on_failure(tool_executor, mock_tool):
    """Test that batch execution continues even if one tool fails."""
    call_count = 0
    
    async def mock_execute(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise ToolExecutionError("Middle tool failed")
        return f"result_{call_count}"
    
    mock_tool.execute = mock_execute
    
    tool_calls = [
        ToolCall(tool_name="mock_tool", args={}),
        ToolCall(tool_name="mock_tool", args={}),
        ToolCall(tool_name="mock_tool", args={}),
    ]
    context = {"user_id": "user1"}
    
    results = await tool_executor.execute_batch(tool_calls, context)
    
    assert len(results) == 3
    assert results[0].success is True
    assert results[1].success is False
    assert results[2].success is True


@pytest.mark.asyncio
async def test_execute_parallel(tool_executor, mock_tool):
    """Test parallel execution runs concurrently."""
    start_times = []
    
    async def mock_execute(**kwargs):
        start_times.append(asyncio.get_event_loop().time())
        await asyncio.sleep(0.1)
        return "result"
    
    mock_tool.execute = mock_execute
    
    tool_calls = [
        ToolCall(tool_name="mock_tool", args={}),
        ToolCall(tool_name="mock_tool", args={}),
        ToolCall(tool_name="mock_tool", args={}),
    ]
    context = {"user_id": "user1"}
    
    results = await tool_executor.execute_parallel(tool_calls, context)
    
    assert len(results) == 3
    # All should start roughly at the same time (within 0.05s)
    assert max(start_times) - min(start_times) < 0.05


@pytest.mark.asyncio
async def test_execute_includes_rationale_in_metadata(tool_executor, mock_tool):
    """Test that tool rationale is included in result metadata."""
    tool_call = ToolCall(
        tool_name="mock_tool",
        args={},
        rationale="This is why we're calling this tool"
    )
    context = {"user_id": "user1"}
    
    result = await tool_executor.execute(tool_call, context)
    
    assert result.metadata.get("rationale") == "This is why we're calling this tool"
