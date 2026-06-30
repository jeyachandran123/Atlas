# 🧠 Memory Module - Quick Reference

## What is it?

The memory module gives your AI assistant **both short-term and long-term memory**, enabling:

- 💬 **Multi-turn conversations** - Remember what was said earlier
- 📚 **Cross-conversation learning** - Recall facts from days ago
- 🎯 **Personalization** - Remember user preferences and patterns
- 🔄 **Automatic learning** - Extract important facts without manual work

## Architecture

```
┌─────────────────────────────────────────────────┐
│          User asks a question                   │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│  1. LOAD MEMORY                                 │
│     • Last 10 messages (session)                │
│     • Top 3 relevant facts (long-term)          │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│  2. AGENT RUNS                                  │
│     • Uses memory context                       │
│     • Generates response                        │
└────────────────┬────────────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────────────┐
│  3. SAVE MEMORY                                 │
│     • Store user message                        │
│     • Store assistant response                  │
│     • Extract learnings (async)                 │
└─────────────────────────────────────────────────┘
```

## Components

### 🔵 Session Memory
**What:** Last 20 messages  
**Where:** Redis List  
**TTL:** 24 hours  
**Speed:** 5-10ms

```python
memory.add_message("user1", "conv1", "user", "Hello")
messages = memory.get_messages("user1", "conv1")
# [{"role": "user", "content": "Hello"}, ...]
```

### 🟢 Long-Term Memory
**What:** Important facts  
**Where:** Redis (V1) → MSSQL+ChromaDB (V2)  
**TTL:** 90 days  
**Speed:** 10-20ms

```python
entry = MemoryEntry(
    content="User prefers TypeScript",
    memory_type="preference",
    importance=0.8,
)
ltm.store(entry)
```

### 🟡 Consolidator
**What:** Automatic fact extraction  
**How:** LLM analyzes conversations  
**When:** After each response (async)

```python
# Automatic in orchestrator
memory.consolidate_async(user_id, org_id, conv_id)

# Extracts:
# ✅ "User prefers TypeScript" (preference, 0.8)
# ✅ "Project uses Jest for testing" (pattern, 0.7)
```

## Usage Patterns

### Pattern 1: Multi-Turn Conversation

```python
# Turn 1
User: "I prefer TypeScript"
Assistant: "Got it! I'll use TypeScript."
[✅ Saved to session memory]

# Turn 2
User: "Show me an example"
Assistant: [Loads session memory, sees TypeScript preference]
"Here's a TypeScript example: ..."
```

### Pattern 2: Cross-Conversation Learning

```python
# Conversation 1 (Monday)
User: "We use Repository pattern for all DB access"
[✅ Extracted to long-term memory: "Repository pattern" (0.9)]

# Conversation 2 (Thursday)
User: "Create a new user service"
Assistant: [Retrieves long-term memory about Repository pattern]
"I'll create it using the Repository pattern: ..."
```

### Pattern 3: Project Context

```python
# Over time, accumulates knowledge
Long-term memories:
1. "User prefers TypeScript" (preference, 0.8)
2. "Project uses Jest for testing" (pattern, 0.7)
3. "Uses Redis for caching" (pattern, 0.8)
4. "Auth bug happens when Redis is down" (issue, 0.9)

# Future questions automatically get this context
User: "Add a caching layer to auth"
Assistant: [Knows: TypeScript, Jest, Redis]
```

## Memory Types

| Type | Example | Use Case |
|------|---------|----------|
| `preference` | "User prefers TypeScript" | Coding style, tools, frameworks |
| `fact` | "This is an e-commerce API" | Project context, architecture |
| `pattern` | "Uses Repository pattern" | Code patterns, best practices |
| `issue` | "Auth fails when Redis is down" | Known bugs, solutions |

## Performance

```
┌─────────────────────┬──────────┬────────────┐
│ Operation           │ Latency  │ Blocking?  │
├─────────────────────┼──────────┼────────────┤
│ Load memory         │ 10-50ms  │ Yes        │
│ Add message         │ 5-10ms   │ Yes        │
│ Consolidate         │ 500ms    │ No (async) │
├─────────────────────┼──────────┼────────────┤
│ Total per request   │ ~20-60ms │ ✅         │
└─────────────────────┴──────────┴────────────┘
```

**Impact:** Adds ~20-60ms to each request (acceptable!)

## Quick Start

### 1. Use in your code

```python
from app.memory import get_memory_manager

memory = get_memory_manager()

# Get context for agent
context = await memory.get_context(
    user_id="user1",
    conversation_id="conv1",
    org_id="org1",
)

# Add messages
await memory.add_message("user1", "conv1", "user", "Hello")
await memory.add_message("user1", "conv1", "assistant", "Hi!")

# Consolidate (fire-and-forget)
await memory.consolidate_async("user1", "org1", "conv1")
```

### 2. Already integrated in orchestrator!

The memory module is **automatically** used in the LangGraph orchestrator:

```python
# Happens automatically:
orchestrator.run(state)
  → load_memory (gets session + long-term)
  → agent runs with memory context
  → finalize (saves messages + consolidates)
```

No manual integration needed! 🎉

## Configuration

### Redis Keys

```
session:{user_id}:{conv_id}          # Session messages
ltmem:index:{user_id}                # Memory index
ltmem:{user_id}:{memory_id}          # Memory data
```

### Settings

```python
SESSION_WINDOW = 20      # Last 20 messages
SESSION_TTL = 86400      # 24 hours
LTM_TTL = 86400 * 90     # 90 days
```

## Testing

```bash
# Unit tests (32 tests)
pytest tests/unit/test_session_memory.py -v
pytest tests/unit/test_long_term_memory.py -v
pytest tests/unit/test_memory_manager.py -v

# Integration test (3 tests)
pytest tests/integration/test_memory_flow.py -v

# All passing ✅
```

## Files

```
app/memory/
├── __init__.py           # Exports
├── session.py            # Session memory
├── long_term.py          # Long-term memory
├── consolidator.py       # Fact extraction
└── manager.py            # Unified interface

tests/
├── unit/
│   ├── test_session_memory.py
│   ├── test_long_term_memory.py
│   └── test_memory_manager.py
└── integration/
    └── test_memory_flow.py

MEMORY_MODULE.md         # Full documentation
MEMORY_COMPLETE.md       # Implementation summary
```

## What's Next? (V2)

🚀 **Planned enhancements:**
- Semantic search with ChromaDB embeddings
- MSSQL persistence for cross-device sync
- Automatic deduplication of similar memories
- Memory pruning (remove low-value facts)
- User management API (view/edit/delete)
- Conversation summarization

## Status

✅ **Phase 1 COMPLETE** - Production Ready  
🚧 **Phase 2 PLANNED** - Semantic search + DB persistence

---

**Version:** 1.1.0  
**Tests:** 35/35 passing ✅  
**Documentation:** Complete ✅  
**Production Ready:** Yes ✅
