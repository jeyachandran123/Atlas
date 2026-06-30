"""
Live test of tool-use loop with real Ollama connection.
Run this after all services are up to verify Phase 1 integration.
"""
import sys
sys.path.insert(0, 'C:/Users/Jayachandran/ProjectsAndDocs/atlas')

from app.agents.tool_planner import ToolPlanner
from app.agents.tool_executor import ToolExecutor
from app.agents.tool_registry import ToolRegistry

def test_tool_planner():
    """Test tool planner with Ollama."""
    print("=" * 60)
    print("TEST 1: Tool Planner")
    print("=" * 60)
    
    planner = ToolPlanner(ollama_host="http://localhost:11434", model="qwen2.5-coder:7b")
    registry = ToolRegistry()
    
    # Test query that should trigger read_file tool
    user_query = "Read the contents of README.md file"
    available_tools = [tool.name for tool in registry.get_all()]
    
    print(f"\nUser Query: {user_query}")
    print(f"Available Tools: {available_tools}")
    
    try:
        tool_calls = planner.plan(user_query, available_tools)
        print(f"\nPlanned Tools ({len(tool_calls)} calls):")
        for call in tool_calls:
            print(f"  - {call.tool_name}: {call.args}")
            print(f"    Rationale: {call.rationale}")
        return True
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False


def test_tool_executor():
    """Test tool executor with read_file."""
    print("\n" + "=" * 60)
    print("TEST 2: Tool Executor")
    print("=" * 60)
    
    executor = ToolExecutor()
    registry = ToolRegistry()
    
    # Create a tool call to read README.md
    from app.shared.schemas import ToolCall
    tool_call = ToolCall(
        tool_name="read_file",
        args={"path": "C:/Users/Jayachandran/ProjectsAndDocs/atlas/README.md"},
        rationale="Read project README"
    )
    
    print(f"\nExecuting: {tool_call.tool_name}")
    print(f"Args: {tool_call.args}")
    
    try:
        result = executor.execute(tool_call, registry)
        print(f"\nResult Status: {'PASS Success' if result.success else 'FAIL Failed'}")
        if result.success:
            content_preview = result.output[:200] + "..." if len(result.output) > 200 else result.output
            print(f"Output Preview: {content_preview}")
        else:
            print(f"Error: {result.error}")
        return result.success
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False


def main():
    """Run all tests."""
    print("\nStarting Live Tool-Use Loop Tests\n")
    
    results = []
    
    # Test 1: Tool Planner
    results.append(("Tool Planner", test_tool_planner()))
    
    # Test 2: Tool Executor  
    results.append(("Tool Executor", test_tool_executor()))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for test_name, success in results:
        status = "PASS" if success else "FAIL"
        print(f"{status} - {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\nAll live tests passed! Phase 1 tool-use loop is working!")
        return 0
    else:
        print("\nSome tests failed. Check errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
