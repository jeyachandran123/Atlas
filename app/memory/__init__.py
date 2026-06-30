"""
Memory system for Atlas AI Coding Assistant.

Provides both short-term (session) and long-term (persistent) memory:

- Session Memory: Last 20 messages stored in Redis, 24h TTL
- Long-Term Memory: Important facts stored in Redis (V1) / MSSQL+ChromaDB (V2)
- Memory Consolidation: Automatic fact extraction from conversations
- Memory Manager: Unified interface for all memory operations

Usage:
    from app.memory import get_memory_manager
    
    memory = get_memory_manager()
    
    # Add messages
    await memory.add_message(user_id, conv_id, "user", "Hello")
    await memory.add_message(user_id, conv_id, "assistant", "Hi!")
    
    # Get context for agent
    context = await memory.get_context(user_id, conv_id, org_id)
    
    # Consolidate learnings (fire-and-forget)
    await memory.consolidate_async(user_id, org_id, conv_id, repo_id)
"""

from app.memory.consolidator import MemoryConsolidator, get_consolidator
from app.memory.long_term import LongTermMemory, MemoryEntry, get_long_term_memory
from app.memory.manager import MemoryManager, get_memory_manager
from app.memory.session import SessionMemory, get_session_memory

__all__ = [
    # Session memory
    "SessionMemory",
    "get_session_memory",
    # Long-term memory
    "LongTermMemory",
    "MemoryEntry",
    "get_long_term_memory",
    # Consolidation
    "MemoryConsolidator",
    "get_consolidator",
    # Manager (main interface)
    "MemoryManager",
    "get_memory_manager",
]
