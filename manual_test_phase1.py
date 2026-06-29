"""
Manual test script for Phase 1: Tool-Use Loop

This script tests the tool-use loop functionality without requiring
the full infrastructure (Docker, DB, etc.) to be running.

Run: python manual_test_phase1.py
"""

import asyncio
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))


async def test_tool_planner():
    """Test 1: Tool Planner"""
    print("\n" + "="*60)
    print("TEST 1: Tool Planner")
    print("="*60)
    
    from app.agents.tool_planner import ToolPlanner
    from app.agents.state import initial_state
    from unittest.mock import AsyncMock
    
    # Mock Ollama
    mock_ollama = AsyncMock()
    planner = ToolPlanner(ollama=mock_ollama)
    
    # Test 1a: No tools needed
    print("\n1a. Testing: General question (no tools needed)")
    mock_ollama.chat.return_value = "[]"
    state = initial_state(
        user_message="What is Python?",
        conversation_id="test1",
        user_id="user1",
        org_id="org1",
        request_id="req1",
    )
    
    tool_calls = await planner.plan(state)
    assert tool_calls == [], f"Expected [], got {tool_calls}"
    print("   ✓ Correctly returned no tools for general question")
    
    # Test 1b: Single tool
    print("\n1b. Testing: Request needing file read")
    mock_ollama.chat.return_value = '[{"tool": "read_file", "args": {"file_path": "test.py"}}]'
    state["user_message"] = "Show me test.py"
    
    tool_calls = await planner.plan(state)
    assert len(tool_calls) == 1, f"Expected 1 tool, got {len(tool_calls)}"
    assert tool_calls[0].tool_name == "read_file"
    assert tool_calls[0].args["file_path"] == "test.py"
    print("   ✓ Correctly planned read_file tool")
    
    # Test 1c: Multiple tools
    print("\n1c. Testing: Request needing multiple tools")
    mock_ollama.chat.return_value = '''[
        {"tool": "search_code", "args": {"query": "auth"}},
        {"tool": "read_file", "args": {"file_path": "app/auth.py"}}
    ]'''
    state["user_message"] = "Find auth code and show me app/auth.py"
    
    tool_calls = await planner.plan(state)
    assert len(tool_calls) == 2, f"Expected 2 tools, got {len(tool_calls)}"
    assert tool_calls[0].tool_name == "search_code"
    assert tool_calls[1].tool_name == "read_file"
    print("   ✓ Correctly planned multiple tools in sequence")
    
    # Test 1d: Max steps reached
    print("\n1d. Testing: Max steps reached")
    state["current_step"] = 5
    state["max_steps"] = 5
    
    tool_calls = await planner.plan(state)
    assert tool_calls == [], "Should return no tools when max steps reached"
    print("   ✓ Correctly skipped planning when max steps reached")
    
    print("\n✅ Tool Planner: ALL TESTS PASSED")
    return True


async def test_tool_executor():
    """Test 2: Tool Executor"""
    print("\n" + "="*60)
    print("TEST 2: Tool Executor")
    print("="*60)
    
    from app.agents.tool_executor import ToolExecutor
    from app.shared.schemas import ToolCall
    from unittest.mock import AsyncMock, MagicMock, patch
    
    # Mock tool and registry
    mock_tool = AsyncMock()
    mock_tool.name = "test_tool"
    mock_tool.execute = AsyncMock(return_value="tool result")
    
    mock_registry = MagicMock()
    mock_registry.get = MagicMock(return_value=mock_tool)
    
    with patch('app.agents.tool_executor.get_tool_registry', return_value=mock_registry):
        executor = ToolExecutor(timeout_seconds=5)
        
        # Test 2a: Successful execution
        print("\n2a. Testing: Successful tool execution")
        tool_call = ToolCall(tool_name="test_tool", args={"arg1": "value1"})
        context = {"user_id": "user1", "org_id": "org1"}
        
        result = await executor.execute(tool_call, context)
        assert result.success is True
        assert result.output == "tool result"
        print("   ✓ Tool executed successfully")
        
        # Test 2b: Tool not found
        print("\n2b. Testing: Tool not found")
        mock_registry.get.return_value = None
        tool_call = ToolCall(tool_name="nonexistent_tool", args={})
        
        result = await executor.execute(tool_call, context)
        assert result.success is False
        assert "not found" in result.error.lower()
        print("   ✓ Handled missing tool correctly")
        
        # Test 2c: Batch execution
        print("\n2c. Testing: Batch execution")
        mock_registry.get.return_value = mock_tool
        tool_calls = [
            ToolCall(tool_name="test_tool", args={"id": 1}),
            ToolCall(tool_name="test_tool", args={"id": 2}),
        ]
        
        results = await executor.execute_batch(tool_calls, context)
        assert len(results) == 2
        assert all(r.success for r in results)
        print("   ✓ Batch execution completed successfully")
    
    print("\n✅ Tool Executor: ALL TESTS PASSED")
    return True


async def test_tool_registry():
    """Test 3: Tool Registry"""
    print("\n" + "="*60)
    print("TEST 3: Tool Registry")
    print("="*60)
    
    from app.agents.tool_registry import ToolRegistry
    
    # Test 3a: Registry initialization
    print("\n3a. Testing: Registry initialization")
    registry = ToolRegistry()
    
    tools = registry.list_tools()
    tool_names = [t.name for t in tools]
    
    expected_tools = ["read_file", "write_file", "search_code", "git_diff", "run_command"]
    
    print(f"   Registered tools: {tool_names}")
    for tool in expected_tools:
        assert tool in tool_names, f"Missing tool: {tool}"
        print(f"   ✓ {tool} registered")
    
    # Test 3b: Get tool by name
    print("\n3b. Testing: Get tool by name")
    read_tool = registry.get("read_file")
    assert read_tool is not None
    assert read_tool.name == "read_file"
    print("   ✓ Successfully retrieved read_file tool")
    
    # Test 3c: Get nonexistent tool
    print("\n3c. Testing: Get nonexistent tool")
    none_tool = registry.get("nonexistent")
    assert none_tool is None
    print("   ✓ Correctly returned None for nonexistent tool")
    
    print("\n✅ Tool Registry: ALL TESTS PASSED")
    return True


async def test_tool_implementations():
    """Test 4: Tool Implementations"""
    print("\n" + "="*60)
    print("TEST 4: Tool Implementations")
    print("="*60)
    
    from app.agents.tools.tool_impls import (
        FileReadTool, FileWriteTool, SearchCodeTool, 
        GitDiffTool, RunCommandTool
    )
    
    # Test 4a: Tool attributes
    print("\n4a. Testing: Tool attributes")
    tools = [
        FileReadTool(),
        FileWriteTool(),
        SearchCodeTool(),
        GitDiffTool(),
        RunCommandTool(),
    ]
    
    for tool in tools:
        assert hasattr(tool, 'name'), f"{tool.__class__.__name__} missing 'name'"
        assert hasattr(tool, 'description'), f"{tool.__class__.__name__} missing 'description'"
        assert hasattr(tool, 'parameters'), f"{tool.__class__.__name__} missing 'parameters'"
        assert hasattr(tool, 'execute'), f"{tool.__class__.__name__} missing 'execute'"
        print(f"   ✓ {tool.name}: All required attributes present")
    
    # Test 4b: Parameter validation
    print("\n4b. Testing: Parameter validation")
    read_tool = FileReadTool()
    assert "file_path" in read_tool.parameters
    assert read_tool.parameters["file_path"]["required"] is True
    print("   ✓ read_file has required file_path parameter")
    
    write_tool = FileWriteTool()
    assert "file_path" in write_tool.parameters
    assert "content" in write_tool.parameters
    print("   ✓ write_file has required parameters")
    
    search_tool = SearchCodeTool()
    assert "query" in search_tool.parameters
    print("   ✓ search_code has required query parameter")
    
    print("\n✅ Tool Implementations: ALL TESTS PASSED")
    return True


async def test_orchestrator_graph():
    """Test 5: Orchestrator Graph Structure"""
    print("\n" + "="*60)
    print("TEST 5: Orchestrator Graph Structure")
    print("="*60)
    
    from app.agents.orchestrator import AgentOrchestrator
    from unittest.mock import AsyncMock
    
    # Test 5a: Graph initialization
    print("\n5a. Testing: Graph initialization")
    mock_vs = AsyncMock()
    orch = AgentOrchestrator(vector_store=mock_vs)
    
    assert hasattr(orch, '_graph'), "Orchestrator missing _graph"
    assert hasattr(orch, '_tool_planner'), "Orchestrator missing _tool_planner"
    assert hasattr(orch, '_tool_executor'), "Orchestrator missing _tool_executor"
    print("   ✓ Orchestrator initialized with required components")
    
    # Test 5b: Node methods exist
    print("\n5b. Testing: Node methods exist")
    required_nodes = [
        '_route_intent_node',
        '_retrieve_context_node',
        '_plan_tools_node',
        '_execute_tools_node',
        '_coding_agent_node',
        '_should_continue_node',
        '_finalise_node',
    ]
    
    for node in required_nodes:
        assert hasattr(orch, node), f"Orchestrator missing {node}"
        print(f"   ✓ {node} exists")
    
    # Test 5c: Graph is compiled
    print("\n5c. Testing: Graph is compiled")
    assert orch._graph is not None, "Graph not compiled"
    print("   ✓ Graph compiled successfully")
    
    print("\n✅ Orchestrator Graph: ALL TESTS PASSED")
    return True


async def test_agent_state():
    """Test 6: Agent State Structure"""
    print("\n" + "="*60)
    print("TEST 6: Agent State Structure")
    print("="*60)
    
    from app.agents.state import initial_state
    
    # Test 6a: Initial state creation
    print("\n6a. Testing: Initial state creation")
    state = initial_state(
        user_message="Test message",
        conversation_id="conv1",
        user_id="user1",
        org_id="org1",
        request_id="req1",
        repo_id="repo1",
    )
    
    # Check all required fields
    required_fields = [
        "user_message", "conversation_id", "user_id", "org_id", "repo_id",
        "request_id", "code_context", "session_messages", "context_block",
        "intent", "tool_calls", "tool_results", "current_step", "max_steps",
        "draft_output", "revision_count", "review_feedback", "final_response",
        "files_modified", "context_chunks_used", "tokens_used", "error"
    ]
    
    for field in required_fields:
        assert field in state, f"State missing field: {field}"
    
    print(f"   ✓ All {len(required_fields)} required fields present")
    
    # Test 6b: Default values
    print("\n6b. Testing: Default values")
    assert state["tool_calls"] == []
    assert state["current_step"] == 0
    assert state["max_steps"] == 5
    assert state["tool_results"] == []
    print("   ✓ Default values correct")
    
    print("\n✅ Agent State: ALL TESTS PASSED")
    return True


async def test_schemas():
    """Test 7: Schemas"""
    print("\n" + "="*60)
    print("TEST 7: Schemas")
    print("="*60)
    
    from app.shared.schemas import ToolCall, ToolResult
    
    # Test 7a: ToolCall schema
    print("\n7a. Testing: ToolCall schema")
    tool_call = ToolCall(
        tool_name="test_tool",
        args={"arg1": "value1"},
        rationale="Test rationale"
    )
    
    assert tool_call.tool_name == "test_tool"
    assert tool_call.args["arg1"] == "value1"
    assert tool_call.rationale == "Test rationale"
    print("   ✓ ToolCall schema works correctly")
    
    # Test 7b: ToolResult schema
    print("\n7b. Testing: ToolResult schema")
    result = ToolResult(
        tool_name="test_tool",
        success=True,
        output="test output",
        error=None,
        metadata={"key": "value"}
    )
    
    assert result.tool_name == "test_tool"
    assert result.success is True
    assert result.output == "test output"
    assert result.metadata["key"] == "value"
    print("   ✓ ToolResult schema works correctly")
    
    print("\n✅ Schemas: ALL TESTS PASSED")
    return True


async def run_all_tests():
    """Run all manual tests"""
    print("\n" + "="*70)
    print(" PHASE 1 MANUAL TESTING - TOOL-USE LOOP")
    print("="*70)
    
    tests = [
        ("Tool Planner", test_tool_planner),
        ("Tool Executor", test_tool_executor),
        ("Tool Registry", test_tool_registry),
        ("Tool Implementations", test_tool_implementations),
        ("Orchestrator Graph", test_orchestrator_graph),
        ("Agent State", test_agent_state),
        ("Schemas", test_schemas),
    ]
    
    results = []
    
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, True, None))
        except Exception as e:
            results.append((name, False, str(e)))
            print(f"\n❌ {name}: FAILED")
            print(f"   Error: {e}")
            import traceback
            traceback.print_exc()
    
    # Summary
    print("\n" + "="*70)
    print(" TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, success, _ in results if success)
    total = len(results)
    
    for name, success, error in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{status}: {name}")
        if error:
            print(f"         Error: {error}")
    
    print("\n" + "="*70)
    print(f" RESULT: {passed}/{total} tests passed")
    if passed == total:
        print(" 🎉 ALL TESTS PASSED - PHASE 1 VERIFIED!")
    else:
        print(f" ⚠️  {total - passed} test(s) failed - needs fixing")
    print("="*70)
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
