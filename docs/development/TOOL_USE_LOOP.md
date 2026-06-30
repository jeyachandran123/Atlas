# Tool-Use Loop Documentation

## Overview

The tool-use loop enables the AI agent to autonomously call tools to gather information and perform actions based on user requests. This makes the agent more capable and reduces the need for users to manually provide context.

## Architecture

```
User: "Show me the auth code and check if there are any security issues"
  ↓
1. Intent Detection: "code" + "review"
  ↓
2. Context Retrieval: Semantic search for "auth code"
  ↓
3. Tool Planning (LLM):
   → Decides: [search_code("authentication"), read_file("app/auth.py")]
  ↓
4. Tool Execution:
   → Executes: search_code → returns 5 auth-related chunks
   → Executes: read_file → returns full auth.py content
  ↓
5. Coding Agent (LLM):
   → Input: Original query + context + tool results
   → Output: "Here's the auth code with security analysis..."
  ↓
6. Should Continue?
   → Agent output analyzed for phrases like "need to check"
   → If yes: loop back to step 3 (max 5 iterations)
   → If no: finalize and return response
```

## Available Tools

### 1. `read_file`
**Purpose:** Read the full content of a file  
**Args:**
- `file_path` (string, required): Path relative to repository root

**Example:**
```json
{
  "tool": "read_file",
  "args": {"file_path": "app/main.py"},
  "rationale": "User asked to see main.py"
}
```

**Safety:** 
- Path traversal protection (can't escape repo)
- Max file size: 5MB
- Binary files rejected

---

### 2. `write_file`
**Purpose:** Write or create a file  
**Args:**
- `file_path` (string, required): Path relative to repository root
- `content` (string, required): Content to write

**Example:**
```json
{
  "tool": "write_file",
  "args": {
    "file_path": "app/new_feature.py",
    "content": "def new_function():\n    pass"
  },
  "rationale": "User requested new feature implementation"
}
```

**Safety:**
- Automatic backup before write
- Max file size: 1MB
- Audit logging for compliance
- Creates parent directories if needed

---

### 3. `search_code`
**Purpose:** Semantic code search  
**Args:**
- `query` (string, required): Natural language description
- `top_k` (integer, optional): Number of results (default: 5, max: 10)

**Example:**
```json
{
  "tool": "search_code",
  "args": {
    "query": "database connection pooling",
    "top_k": 5
  },
  "rationale": "Find how DB connections are managed"
}
```

**Returns:** List of code chunks with file path, lines, score, and preview

---

### 4. `git_diff`
**Purpose:** Show uncommitted changes  
**Args:**
- `file_path` (string, optional): Specific file to diff

**Example:**
```json
{
  "tool": "git_diff",
  "args": {},
  "rationale": "User asked what changed"
}
```

**Returns:** Unified diff format or "No uncommitted changes found"

---

### 5. `run_command`
**Purpose:** Execute shell commands (read-only preferred)  
**Args:**
- `command` (string, required): Shell command to execute

**Example:**
```json
{
  "tool": "run_command",
  "args": {"command": "pytest tests/test_auth.py -v"},
  "rationale": "Run auth tests"
}
```

**Safety:**
- Dangerous commands blocked (rm, del, format, etc.)
- 30-second timeout
- Runs in repository directory
- Output limited to prevent overwhelming responses

---

## Tool Planning Logic

The tool planner uses a lightweight LLM call to decide which tools to call. It considers:

1. **User intent:** What is the user asking for?
2. **Available context:** Do we already have the information?
3. **Tool capabilities:** Which tools can fulfill the request?
4. **Previous results:** What have we already discovered?

**Planning prompt structure:**
```
Available tools: [list of tools with descriptions]
User request: {user_message}
Current context: 
  - Intent: {intent}
  - Repository: {repo_id}
  - Previous tool results: {count}

Respond with JSON array of tool calls or []
```

**Example planning decisions:**

| User Request | Planned Tools | Rationale |
|-------------|---------------|-----------|
| "What is Python?" | `[]` | General knowledge, no tools needed |
| "Show me main.py" | `[read_file("main.py")]` | Direct file request |
| "Find auth code" | `[search_code("authentication")]` | Semantic search needed |
| "Show main.py and find DB code" | `[read_file("main.py"), search_code("database")]` | Multiple tools in sequence |

---

## Loop Control

### Maximum Iterations
- **Default:** 5 steps
- **Configurable:** Set `max_steps` in AgentState
- **Reason:** Prevent infinite loops and excessive API costs

### Loop Continuation Logic

The agent continues if:
1. `current_step < max_steps` AND
2. Agent output contains phrases like:
   - "need to see"
   - "need to check"
   - "need to read"
   - "let me search"
   - "let me check"
   - "i need to"

**Example:**
```
Agent (step 1): "I found the auth code. Let me check for security issues..."
  → Loop continues, re-plans tools

Agent (step 2): "Here's the complete analysis with recommendations."
  → Loop exits, finalizes response
```

---

## Error Handling

### Tool Execution Failures
- **Behavior:** Tool returns `ToolResult(success=False, error="...")`
- **Impact:** Agent receives error in context, can explain or retry
- **Example:** File not found → Agent says "I couldn't find that file"

### Tool Timeouts
- **Timeout:** 30 seconds per tool
- **Behavior:** Returns timeout error, continues pipeline
- **Example:** Slow command → Agent suggests running manually

### Planning Failures
- **Behavior:** Returns empty list `[]`, agent responds with available context
- **Impact:** Graceful degradation - still provides helpful response

### Max Steps Reached
- **Behavior:** Loop exits, finalizes current draft_output
- **Impact:** Agent provides partial answer with note about complexity

---

## Adding New Tools

### 1. Create Tool Class
```python
# app/agents/tools/tool_impls.py

class MyNewTool(BaseTool):
    name = "my_new_tool"
    description = "What this tool does"
    parameters = {
        "param1": {
            "type": "string",
            "description": "What param1 is for",
            "required": True,
        }
    }

    async def execute(self, context: dict, **kwargs: Any) -> Any:
        param1 = kwargs.get("param1")
        # Tool logic here
        return result
```

### 2. Register Tool
```python
# app/agents/tool_registry.py

def _register_default_tools(self) -> None:
    # ... existing tools ...
    self.register(MyNewTool())
```

### 3. Update Planning Prompt
```python
# app/agents/tool_planner.py

TOOL_PLANNING_PROMPT = """
Available tools:
# ... existing tools ...
6. my_new_tool(param1: str) -> result
   - What it does
   - When to use it
"""
```

### 4. Add Tests
```python
# tests/unit/test_my_new_tool.py

@pytest.mark.asyncio
async def test_my_new_tool():
    tool = MyNewTool()
    result = await tool.execute(
        context={"user_id": "test"},
        param1="test_value"
    )
    assert result == expected
```

---

## Performance Considerations

### Latency Impact
- Each tool call adds ~200-500ms (file read/search)
- LLM planning adds ~500-1000ms per iteration
- **Total:** 1-5 additional seconds depending on tool count

### Optimization Strategies
1. **Minimize tool calls:** Agent should only call when necessary
2. **Batch operations:** Future enhancement - parallel tool execution
3. **Caching:** Tool results cached within conversation
4. **Smart planning:** LLM learns when NOT to call tools

### Cost Impact
- Planning calls: ~200 tokens per iteration
- Agent calls: ~1000-2000 tokens per iteration
- **Total:** 1200-2200 tokens per iteration × iterations

---

## Testing

### Unit Tests
```bash
pytest tests/unit/test_tool_planner.py -v
pytest tests/unit/test_tool_executor.py -v
```

### Integration Tests
```bash
pytest tests/integration/test_tool_loop.py -v
```

### Manual Testing
```python
# Test tool planning
from app.agents.tool_planner import get_tool_planner
from app.agents.state import initial_state

state = initial_state(
    user_message="Find authentication code",
    conversation_id="test",
    user_id="user1",
    org_id="org1",
    request_id="req1",
    repo_id="repo1",
)

planner = get_tool_planner()
tools = await planner.plan(state)
print(tools)  # [ToolCall(tool_name='search_code', ...)]
```

---

## Future Enhancements (V2)

1. **Parallel tool execution** for independent tools
2. **Tool result caching** across conversations
3. **Custom tool definitions** via configuration
4. **Tool usage analytics** for optimization
5. **Conditional tool execution** based on confidence scores
6. **Tool chaining** - tools can call other tools

---

## Troubleshooting

### Problem: Agent not calling tools
**Diagnosis:** Check tool planner output  
**Solution:** Improve planning prompt with more examples

### Problem: Tool loop never exits
**Diagnosis:** Agent keeps saying "need to check"  
**Solution:** Reduce max_steps or improve agent prompt

### Problem: Tool execution fails
**Diagnosis:** Check tool logs and error messages  
**Solution:** Verify repository path, file permissions, etc.

### Problem: Slow responses
**Diagnosis:** Too many tool iterations  
**Solution:** Optimize planning to call fewer tools

---

## Implementation Files

### Core Modules
- `app/agents/state.py` - Extended with tool_calls, current_step, max_steps
- `app/agents/tool_planner.py` - LLM-based tool planning
- `app/agents/tool_executor.py` - Tool execution with timeout protection
- `app/agents/tool_registry.py` - Central tool registration
- `app/agents/orchestrator.py` - Updated graph with tool loop nodes

### Tool Implementations
- `app/agents/tools/tool_impls.py` - All 5 tools (read, write, search, git, command)
- `app/shared/schemas.py` - ToolCall and ToolResult schemas
- `app/shared/exceptions.py` - ToolExecutionError

### Tests
- `tests/unit/test_tool_planner.py` - 8 unit tests
- `tests/unit/test_tool_executor.py` - 10 unit tests
- `tests/integration/test_tool_loop.py` - 6 integration tests

---

## References

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Tool Use Patterns](https://docs.anthropic.com/claude/docs/tool-use)
- [README.md](./README.md) - Main project documentation

---

**Status:** ✅ Phase 1 Complete - Production Ready  
**Version:** 1.1.0  
**Last Updated:** 2024
