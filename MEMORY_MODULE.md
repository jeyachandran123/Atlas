# Memory Module Documentation

## Overview

The memory module provides both **short-term (session)** and **long-term (persistent)** memory for multi-turn conversations. This enables the AI agent to:

- Remember previous messages in the conversation
- Recall important facts and preferences across conversations
- Learn from past interactions
- Provide contextually aware responses

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Memory Manager                           │
│  (Unified interface for all memory operations)             │
└─────────────┬──────────────────────────┬───────────────────┘
              │                          │
              ▼                          ▼
    ┌──────────────────┐      ┌──────────────────────┐
    │ Session Memory   │      │ Long-Term Memory     │
    │                  │      │                      │
    │ - Last 20 msgs   │      │ - Important facts    │
    │ - Redis storage  │      │ - Redis (V1)         │
    │ - 24h TTL        │      │ - MSSQL+ChromaDB(V2) │
    │ - Fast access    │      │ - 90-day TTL         │
    └──────────────────┘      └──────────────────────┘
                                      ▲
                                      │
                              ┌───────┴────────┐
                              │ Consolidator   │
                              │                │
                              │ - LLM extract  │
                              │ - Auto-learn   │
                              └────────────────┘
```

## Components

### 1. Session Memory

**Purpose:** Store recent conversation history for immediate context

**Storage:** Redis List (LPUSH/LRANGE)  
**TTL:** 24 hours  
**Capacity:** Last 20 messages per conversation

**Usage:**
```python
from app.memory import get_session_memory

memory = get_session_memory()

# Add message
await memory.add_message(
    user_id="user1",
    conversation_id="conv1",
    role="user",
    content="Hello, how do I fix this bug?"
)

# Get messages
messages = await memory.get_messages("user1", "conv1", limit=10)
# Returns: [{"role": "user", "content": "..."}, ...]

# Get formatted for LLM
context = await memory.get_formatted_context("user1", "conv1")
# Returns:
# """
# Previous conversation:
# User: Hello, how do I fix this bug?
# Assistant: Let me help you with that...
# """
```

**Features:**
- Automatic sliding window (LTRIM keeps last N)
- Chronological ordering (newest messages last)
- Automatic expiry after 24h of inactivity
- Per-conversation isolation

---

### 2. Long-Term Memory

**Purpose:** Store important facts that should persist across conversations

**Storage:** Redis Hash (V1) → MSSQL + ChromaDB (V2)  
**TTL:** 90 days  
**Capacity:** Unlimited (filtered by importance)

**Memory Types:**
- `preference` - User preferences and coding style
- `fact` - Project-specific context and architecture  
- `pattern` - Code patterns and best practices
- `issue` - Recurring bugs and solutions

**Usage:**
```python
from app.memory import get_long_term_memory, MemoryEntry

ltm = get_long_term_memory()

# Store a memory
entry = MemoryEntry(
    user_id="user1",
    org_id="org1",
    content="User prefers TypeScript over JavaScript for type safety",
    memory_type="preference",
    importance=0.8,
    repo_id="repo1",
    source_conversation_id="conv1",
)
await ltm.store(entry)

# Retrieve relevant memories
memories = await ltm.retrieve(
    user_id="user1",
    query="typescript preferences",  # Optional semantic search (V2)
    repo_id="repo1",  # Optional filter
    memory_type="preference",  # Optional filter
    limit=5,
)

# Get formatted for LLM
context = await ltm.get_formatted_context("user1", repo_id="repo1")
# Returns:
# """
# Relevant context from past conversations:
# - User prefers TypeScript over JavaScript for type safety
# - Project uses Repository pattern for database access
# """
```

**Features:**
- Importance scoring (0-1)
- Access tracking (counts, last accessed)
- Filter by repository, type
- Semantic search (V2 with ChromaDB)
- Automatic deduplication (V2)

---

### 3. Memory Consolidator

**Purpose:** Automatically extract important facts from conversations

**How it works:**
1. After each conversation turn, analyze messages
2. Use LLM to identify facts worth remembering
3. Score importance (0-1)
4. Store in long-term memory

**Usage:**
```python
from app.memory import get_consolidator

consolidator = get_consolidator()

# Blocking version (wait for completion)
count = await consolidator.consolidate(
    user_id="user1",
    org_id="org1",
    conversation_id="conv1",
    messages=[
        {"role": "user", "content": "I prefer TypeScript"},
        {"role": "assistant", "content": "Got it! I'll use TypeScript."},
    ],
    repo_id="repo1",
)
print(f"Extracted {count} facts")

# Fire-and-forget version (don't block response)
await consolidator.consolidate_async(...)
```

**Extraction Examples:**

Input conversation:
```
User: I prefer using Jest for testing
Assistant: Got it! I'll use Jest for the tests.
User: Also, we use Repository pattern for all DB access
Assistant: Understood. I'll follow that pattern.
```

Extracted facts:
```json
[
  {
    "content": "User prefers Jest for testing",
    "type": "preference",
    "importance": 0.7
  },
  {
    "content": "Project uses Repository pattern for database access",
    "type": "pattern",
    "importance": 0.9
  }
]
```

---

### 4. Memory Manager

**Purpose:** Unified interface for all memory operations

**Usage:**
```python
from app.memory import get_memory_manager

memory = get_memory_manager()

# Add messages (session memory)
await memory.add_message("user1", "conv1", "user", "Hello")
await memory.add_message("user1", "conv1", "assistant", "Hi!")

# Get complete context (session + long-term)
context = await memory.get_context(
    user_id="user1",
    conversation_id="conv1",
    org_id="org1",
    repo_id="repo1",
    query="authentication",  # Optional semantic search
    session_limit=10,  # Last 10 messages
    ltm_limit=3,  # Top 3 relevant memories
)

# Consolidate learnings (fire-and-forget)
await memory.consolidate_async("user1", "org1", "conv1", "repo1")

# Cleanup
await memory.clear_session("user1", "conv1")
await memory.delete_memory("user1", "mem_id")
```

---

## Integration with Orchestrator

The memory module is integrated into the LangGraph orchestrator:

### Graph Flow

```
START
  ↓
route_intent        (detect user intent)
  ↓
load_memory         (NEW: load session + long-term memory)
  ↓
retrieve_context    (fetch code from ChromaDB)
  ↓
plan_tools         (decide which tools to call)
  ↓
[tool loop...]
  ↓
finalise           (NEW: save messages + consolidate learnings)
  ↓
END
```

### Load Memory Node

```python
async def _load_memory_node(self, state: AgentState) -> AgentState:
    # Get memory context (both session and long-term)
    memory_context = await self._memory.get_context(
        user_id=state["user_id"],
        conversation_id=state["conversation_id"],
        org_id=state["org_id"],
        repo_id=state.get("repo_id"),
        query=state["user_message"],
        session_limit=10,
        ltm_limit=3,
    )
    
    return {
        **state,
        "memory_context": memory_context,
    }
```

### Finalize Node

```python
async def _finalise_node(self, state: AgentState) -> AgentState:
    # Save messages to session memory
    await self._memory.add_message(
        user_id=state["user_id"],
        conversation_id=state["conversation_id"],
        role="user",
        content=state["user_message"],
    )
    
    await self._memory.add_message(
        user_id=state["user_id"],
        conversation_id=state["conversation_id"],
        role="assistant",
        content=state["final_response"],
    )
    
    # Extract learnings (async, non-blocking)
    await self._memory.consolidate_async(
        user_id=state["user_id"],
        org_id=state["org_id"],
        conversation_id=state["conversation_id"],
        repo_id=state.get("repo_id"),
    )
    
    return {**state, "final_response": state["final_response"]}
```

---

## Configuration

### Redis Keys

```
# Session memory
session:{user_id}:{conversation_id}  → List of messages

# Long-term memory index
ltmem:index:{user_id}  → Set of memory IDs

# Long-term memory entry
ltmem:{user_id}:{memory_id}  → JSON memory data
```

### Settings

```python
# Session memory
SESSION_WINDOW = 20  # Last N messages
SESSION_TTL = 86400  # 24 hours

# Long-term memory
LTM_TTL = 86400 * 90  # 90 days

# Consolidation
MIN_MESSAGES_FOR_CONSOLIDATION = 4  # Need meaningful conversation
```

---

## Performance

### Latency Impact

| Operation | Latency | Blocking? |
|-----------|---------|-----------|
| Load memory | ~10-50ms | Yes (in graph) |
| Add message | ~5-10ms | Yes (after response) |
| Consolidate | ~500-1000ms | No (fire-and-forget) |

**Total impact:** ~20-60ms added to each request (load + save)

### Redis Usage

- Session: ~1 KB per message × 20 = ~20 KB per conversation
- Long-term: ~500 B per memory × 50 = ~25 KB per user
- Total: ~45 KB per active user (negligible)

---

## V2 Enhancements

### Planned for V2

1. **Semantic search in long-term memory**
   - Embed memories in ChromaDB
   - Retrieve by similarity instead of just importance

2. **MSSQL persistence**
   - Store long-term memories in database
   - Enable cross-device sync, analytics, search

3. **Automatic deduplication**
   - Detect similar memories
   - Merge or update instead of creating duplicates

4. **Memory pruning**
   - Automatically remove low-value memories
   - Based on: low importance, never accessed, stale

5. **User-managed memories**
   - API endpoints to view/edit/delete memories
   - UI for memory management

6. **Conversation summarization**
   - Compress old conversations
   - Replace message-by-message with summary

---

## Testing

### Unit Tests

```bash
# Test session memory
pytest tests/unit/test_session_memory.py -v

# Test long-term memory
pytest tests/unit/test_long_term_memory.py -v

# Test memory manager
pytest tests/unit/test_memory_manager.py -v
```

### Integration Test

```python
# Test full memory flow
memory = get_memory_manager()

# Add conversation
await memory.add_message("user1", "conv1", "user", "I prefer Python")
await memory.add_message("user1", "conv1", "assistant", "Noted!")

# Get context
context = await memory.get_context("user1", "conv1", "org1")
assert "I prefer Python" in context

# Consolidate
count = await memory.consolidate("user1", "org1", "conv1")
assert count >= 0

# Retrieve long-term
ltm = get_long_term_memory()
memories = await ltm.retrieve("user1", query="python")
assert len(memories) > 0
```

---

## Troubleshooting

### Problem: Memory not loading

**Diagnosis:**
- Check Redis connection
- Verify user_id/conversation_id are correct
- Check Redis key exists: `redis-cli get session:user1:conv1`

**Solution:**
```bash
# Test Redis
docker exec aic_redis redis-cli ping

# Check keys
docker exec aic_redis redis-cli keys "session:*"
```

### Problem: Consolidation not working

**Diagnosis:**
- Check Ollama is running
- Verify LLM model is available
- Check logs for extraction errors

**Solution:**
```bash
# Test Ollama
curl http://localhost:11434/api/tags

# Check logs
docker logs aic_api | grep consolidat
```

### Problem: Memory context not in agent response

**Diagnosis:**
- Check `memory_context` field in AgentState
- Verify coding agent is using memory_context

**Solution:**
- Update prompt template to include `{memory_context}`
- Check orchestrator load_memory_node is executing

---

## Files

### Core Modules
- `app/memory/session.py` - Session memory (Redis List)
- `app/memory/long_term.py` - Long-term memory (Redis Hash → DB)
- `app/memory/consolidator.py` - Fact extraction (LLM-based)
- `app/memory/manager.py` - Unified interface
- `app/memory/__init__.py` - Public exports

### Tests
- `tests/unit/test_session_memory.py` - 8 tests
- `tests/unit/test_long_term_memory.py` - 12 tests
- `tests/unit/test_memory_manager.py` - 12 tests

### Integration
- `app/agents/orchestrator.py` - Memory integration in graph
- `app/agents/state.py` - Added `memory_context` field

---

## Status

✅ **Phase 1 Complete** — Session + Long-term memory (Redis-based)  
🚧 **Phase 2 Planned** — Semantic search, MSSQL persistence, deduplication

**Version:** 1.1.0  
**Last Updated:** 2024
