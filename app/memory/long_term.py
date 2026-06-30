"""
Long-term memory — persistent knowledge across conversations.

Stores important facts, patterns, and learnings that should persist
beyond the 20-message session window.

Examples:
- User preferences: "I prefer TypeScript over JavaScript"
- Project context: "This is an e-commerce API built with FastAPI"
- Recurring issues: "Auth bug happens when Redis is down"
- Code patterns: "We use Repository pattern for DB access"

Implementation:
- Stored in MSSQL for persistence and queryability
- Embedded in ChromaDB for semantic retrieval
- Automatically extracted from conversations (V2 feature)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from loguru import logger


class MemoryEntry:
    """
    A single long-term memory entry.
    
    Attributes:
        id: Unique identifier
        user_id: User who owns this memory
        org_id: Organization scope
        repo_id: Optional repository scope
        memory_type: Type of memory (preference, fact, pattern, issue)
        content: The actual memory text
        importance: Score 0-1 indicating how important this is
        source_conversation_id: Where this memory came from
        created_at: When this was created
        accessed_count: How many times this has been retrieved
        last_accessed_at: When this was last used
    """

    def __init__(
        self,
        user_id: str,
        org_id: str,
        content: str,
        memory_type: str = "fact",
        importance: float = 0.5,
        repo_id: Optional[str] = None,
        source_conversation_id: Optional[str] = None,
        id: Optional[str] = None,
        created_at: Optional[datetime] = None,
        accessed_count: int = 0,
        last_accessed_at: Optional[datetime] = None,
    ):
        self.id = id or str(uuid.uuid4())
        self.user_id = user_id
        self.org_id = org_id
        self.repo_id = repo_id
        self.memory_type = memory_type
        self.content = content
        self.importance = importance
        self.source_conversation_id = source_conversation_id
        self.created_at = created_at or datetime.now(timezone.utc)
        self.accessed_count = accessed_count
        self.last_accessed_at = last_accessed_at

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "org_id": self.org_id,
            "repo_id": self.repo_id,
            "memory_type": self.memory_type,
            "content": self.content,
            "importance": self.importance,
            "source_conversation_id": self.source_conversation_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "accessed_count": self.accessed_count,
            "last_accessed_at": self.last_accessed_at.isoformat() if self.last_accessed_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MemoryEntry:
        """Create from dictionary."""
        return cls(
            id=data.get("id"),
            user_id=data["user_id"],
            org_id=data["org_id"],
            repo_id=data.get("repo_id"),
            memory_type=data.get("memory_type", "fact"),
            content=data["content"],
            importance=data.get("importance", 0.5),
            source_conversation_id=data.get("source_conversation_id"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
            accessed_count=data.get("accessed_count", 0),
            last_accessed_at=datetime.fromisoformat(data["last_accessed_at"]) if data.get("last_accessed_at") else None,
        )


class LongTermMemory:
    """
    Manages long-term memory storage and retrieval.
    
    V1: Simple Redis-based storage with JSON serialization
    V2: MSSQL + ChromaDB for persistence and semantic search
    """

    def __init__(self):
        self._use_db = False  # V1: Redis only, V2: Enable DB + vector store

    async def store(self, entry: MemoryEntry) -> None:
        """
        Store a memory entry.
        
        Args:
            entry: MemoryEntry to store
        """
        try:
            from app.redis_client import get_redis
            
            # Store in Redis for now (V1)
            key = f"ltmem:{entry.user_id}:{entry.id}"
            r = get_redis()
            await r.set(key, json.dumps(entry.to_dict()), ex=86400 * 90)  # 90-day TTL
            
            # Add to user's memory index
            index_key = f"ltmem:index:{entry.user_id}"
            await r.sadd(index_key, entry.id)
            await r.expire(index_key, 86400 * 90)
            
            logger.debug(f"Stored long-term memory: {entry.id}")
            
        except Exception as e:
            logger.error(f"Failed to store long-term memory: {e}")

    async def retrieve(
        self,
        user_id: str,
        query: Optional[str] = None,
        repo_id: Optional[str] = None,
        memory_type: Optional[str] = None,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        """
        Retrieve relevant memories.
        
        Args:
            user_id: User ID to retrieve memories for
            query: Optional semantic query (V2: uses embeddings)
            repo_id: Optional filter by repository
            memory_type: Optional filter by type
            limit: Maximum number of memories to return
        
        Returns:
            List of MemoryEntry objects sorted by relevance/importance
        """
        try:
            from app.redis_client import get_redis
            
            r = get_redis()
            index_key = f"ltmem:index:{user_id}"
            
            # Get all memory IDs for this user
            memory_ids = await r.smembers(index_key)
            if not memory_ids:
                return []
            
            # Fetch all memories
            memories = []
            for mem_id in memory_ids:
                key = f"ltmem:{user_id}:{mem_id}"
                data = await r.get(key)
                if data:
                    try:
                        entry = MemoryEntry.from_dict(json.loads(data))
                        
                        # Apply filters
                        if repo_id and entry.repo_id != repo_id:
                            continue
                        if memory_type and entry.memory_type != memory_type:
                            continue
                        
                        memories.append(entry)
                    except Exception as e:
                        logger.warning(f"Failed to parse memory {mem_id}: {e}")
            
            # Sort by importance (V2: will use semantic similarity)
            memories.sort(key=lambda m: m.importance, reverse=True)
            
            # Update access tracking
            now = datetime.now(timezone.utc)
            for mem in memories[:limit]:
                mem.accessed_count += 1
                mem.last_accessed_at = now
                await self.store(mem)  # Update in storage
            
            return memories[:limit]
            
        except Exception as e:
            logger.error(f"Failed to retrieve long-term memories: {e}")
            return []

    async def delete(self, user_id: str, memory_id: str) -> bool:
        """
        Delete a specific memory.
        
        Args:
            user_id: User ID
            memory_id: Memory ID to delete
        
        Returns:
            True if deleted, False if not found
        """
        try:
            from app.redis_client import get_redis
            
            r = get_redis()
            key = f"ltmem:{user_id}:{memory_id}"
            deleted = await r.delete(key)
            
            # Remove from index
            index_key = f"ltmem:index:{user_id}"
            await r.srem(index_key, memory_id)
            
            return deleted > 0
            
        except Exception as e:
            logger.error(f"Failed to delete memory: {e}")
            return False

    async def get_formatted_context(
        self,
        user_id: str,
        query: Optional[str] = None,
        repo_id: Optional[str] = None,
        limit: int = 3,
    ) -> str:
        """
        Get long-term memories formatted for LLM context.
        
        Returns:
            Formatted string with relevant memories
        """
        memories = await self.retrieve(
            user_id=user_id,
            query=query,
            repo_id=repo_id,
            limit=limit,
        )
        
        if not memories:
            return ""
        
        lines = ["Relevant context from past conversations:"]
        for mem in memories:
            lines.append(f"- {mem.content}")
        
        return "\n".join(lines)


# Singleton instance
_long_term_memory: LongTermMemory | None = None


def get_long_term_memory() -> LongTermMemory:
    """Get the singleton long-term memory instance."""
    global _long_term_memory
    if _long_term_memory is None:
        _long_term_memory = LongTermMemory()
    return _long_term_memory
