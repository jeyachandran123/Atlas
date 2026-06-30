"""
Phase 1 Validation Script - Structure Check

This script validates that all Phase 1 files and components are in place
without requiring dependencies to be installed.
"""

import os
import ast
from pathlib import Path


def check_file_exists(filepath, description):
    """Check if a file exists"""
    exists = os.path.exists(filepath)
    status = "[OK]" if exists else "[MISS]"
    print(f"  {status} {description}")
    return exists


def check_function_exists(filepath, function_name):
    """Check if a function exists in a Python file"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read())
        
        functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
        exists = function_name in functions
        status = "[OK]" if exists else "[MISS]"
        print(f"    {status} Function: {function_name}")
        return exists
    except Exception as e:
        print(f"    [ERR] Error checking {filepath}: {e}")
        return False


def check_class_exists(filepath, class_name):
    """Check if a class exists in a Python file"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read())
        
        classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
        exists = class_name in classes
        status = "[OK]" if exists else "[MISS]"
        print(f"    {status} Class: {class_name}")
        return exists
    except Exception as e:
        print(f"    [ERR] Error checking {filepath}: {e}")
        return False


def main():
    print("="*70)
    print(" PHASE 1 VALIDATION - STRUCTURE CHECK")
    print("="*70)
    
    results = []
    
    # 1. Check core files exist
    print("\n[1] Core Files:")
    files = [
        ("app/agents/tool_planner.py", "Tool Planner Module"),
        ("app/agents/tool_executor.py", "Tool Executor Module"),
        ("app/agents/tool_registry.py", "Tool Registry Module"),
        ("app/agents/tools/tool_impls.py", "Tool Implementations"),
        ("TOOL_USE_LOOP.md", "Documentation"),
    ]
    
    for filepath, desc in files:
        results.append(check_file_exists(filepath, desc))
    
    # 2. Check test files exist
    print("\n[2] Test Files:")
    test_files = [
        ("tests/unit/test_tool_planner.py", "Tool Planner Tests"),
        ("tests/unit/test_tool_executor.py", "Tool Executor Tests"),
        ("tests/integration/test_tool_loop.py", "Integration Tests"),
    ]
    
    for filepath, desc in test_files:
        results.append(check_file_exists(filepath, desc))
    
    # 3. Check tool_planner.py structure
    print("\n[3] Tool Planner Structure:")
    if os.path.exists("app/agents/tool_planner.py"):
        results.append(check_class_exists("app/agents/tool_planner.py", "ToolPlanner"))
        results.append(check_function_exists("app/agents/tool_planner.py", "plan"))
        results.append(check_function_exists("app/agents/tool_planner.py", "get_tool_planner"))
    else:
        results.extend([False, False, False])
    
    # 4. Check tool_executor.py structure
    print("\n[4] Tool Executor Structure:")
    if os.path.exists("app/agents/tool_executor.py"):
        results.append(check_class_exists("app/agents/tool_executor.py", "ToolExecutor"))
        results.append(check_function_exists("app/agents/tool_executor.py", "execute"))
        results.append(check_function_exists("app/agents/tool_executor.py", "execute_batch"))
    else:
        results.extend([False, False, False])
    
    # 5. Check tool_registry.py structure
    print("\n[5] Tool Registry Structure:")
    if os.path.exists("app/agents/tool_registry.py"):
        results.append(check_class_exists("app/agents/tool_registry.py", "ToolRegistry"))
        results.append(check_function_exists("app/agents/tool_registry.py", "register"))
        results.append(check_function_exists("app/agents/tool_registry.py", "get"))
    else:
        results.extend([False, False, False])
    
    # 6. Check tool implementations
    print("\n[6] Tool Implementations:")
    if os.path.exists("app/agents/tools/tool_impls.py"):
        tools = [
            "FileReadTool",
            "FileWriteTool",
            "SearchCodeTool",
            "GitDiffTool",
            "RunCommandTool"
        ]
        for tool in tools:
            results.append(check_class_exists("app/agents/tools/tool_impls.py", tool))
    else:
        results.extend([False] * 5)
    
    # 7. Check orchestrator updates
    print("\n[7] Orchestrator Updates:")
    if os.path.exists("app/agents/orchestrator.py"):
        results.append(check_function_exists("app/agents/orchestrator.py", "_plan_tools_node"))
        results.append(check_function_exists("app/agents/orchestrator.py", "_execute_tools_node"))
        results.append(check_function_exists("app/agents/orchestrator.py", "_should_continue_node"))
    else:
        results.extend([False, False, False])
    
    # 8. Check state.py updates
    print("\n[8] Agent State Updates:")
    if os.path.exists("app/agents/state.py"):
        with open("app/agents/state.py", 'r', encoding='utf-8') as f:
            content = f.read()
        
        checks = [
            ("tool_calls", "tool_calls field"),
            ("current_step", "current_step field"),
            ("max_steps", "max_steps field"),
        ]
        
        for field, desc in checks:
            exists = field in content
            status = "[OK]" if exists else "[MISS]"
            print(f"    {status} {desc}")
            results.append(exists)
    else:
        results.extend([False, False, False])
    
    # 9. Check schemas.py updates
    print("\n[9] Schema Updates:")
    if os.path.exists("app/shared/schemas.py"):
        results.append(check_class_exists("app/shared/schemas.py", "ToolCall"))
        with open("app/shared/schemas.py", 'r', encoding='utf-8') as f:
            content = f.read()
        has_toolresult = "class ToolResult" in content
        status = "[OK]" if has_toolresult else "[MISS]"
        print(f"    {status} Class: ToolResult")
        results.append(has_toolresult)
    else:
        results.extend([False, False])
    
    # 10. Check documentation
    print("\n[10] Documentation:")
    if os.path.exists("TOOL_USE_LOOP.md"):
        with open("TOOL_USE_LOOP.md", 'r', encoding='utf-8') as f:
            content = f.read()
        
        checks = [
            ("Available Tools", "Tool descriptions"),
            ("read_file", "read_file tool"),
            ("write_file", "write_file tool"),
            ("search_code", "search_code tool"),
            ("Tool Planning Logic", "Planning documentation"),
            ("Loop Control", "Loop control documentation"),
        ]
        
        for keyword, desc in checks:
            exists = keyword in content
            status = "[OK]" if exists else "[MISS]"
            print(f"    {status} {desc}")
            results.append(exists)
    else:
        results.extend([False] * 6)
    
    # Summary
    print("\n" + "="*70)
    print(" VALIDATION SUMMARY")
    print("="*70)
    
    passed = sum(results)
    total = len(results)
    percentage = (passed / total) * 100 if total > 0 else 0
    
    print(f"\nChecks Passed: {passed}/{total} ({percentage:.1f}%)")
    
    if passed == total:
        print("\n[SUCCESS] All Phase 1 components are in place!")
        print("          The tool-use loop is structurally complete.")
        return 0
    else:
        print(f"\n[WARNING] {total - passed} checks failed")
        print("          Some components may be missing or incomplete.")
        return 1


if __name__ == "__main__":
    exit(main())
