"""
Memory manager — unified interface for all memory operations.

Orchestrates session memory (short-term) and long-term memory
to provide a complete memory system for the agent.

Usage in orchestrator:
    memory = get_memory_manager()
    
    # Get context for agent
    context = await memory.get_context(user_id, conversation_id)
    
    # After agent response
    await memory.add_message(user_id, conversation_id, "user", user_message)
    await memory.add_message(user_id, conversation_id, "assistant", agent_response)
    
    # Consolidate learnings (async, non-blocking)
    await memory.consolidate_async(user_id, org_id, conversation_id)
"""

from __future__ import annotations

from typing import Optional

from loguru import logger

from app.memory.consolidator import MemoryConsolidator, get_consolidator
from app.memory.long_term import LongTermMemory, get_long_term_memory
from app.memory.session import SessionMemory, get_session_memory


class MemoryManager:
    """
    Unified memory management interface.
    
    Combines:
    - Session memory (last 20 messages, Redis, fast)
    - Long-term memory (important facts, Redis/DB, persistent)
    - Memory consolidation (extract facts from conversations)
    """

    def __init__(
        self,
        session: Optional[SessionMemory] = None,
        long_term: Optional[LongTermMemory] = None,
        consolidator: Optional[MemoryConsolidator] = None,
    ):
        self.session = session or get_session_memory()
        self.long_term = long_term or get_long_term_memory()
        self.consolidator = consolidator or get_consolidator()

    # ─────────────────────────────────────────────────────────────────────────
    # Message Management
    # ─────────────────────────────────────────────────────────────────────────

    async def add_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
    ) -> None:
        """
        Add a message to session memory.
        
        Args:
            user_id: User ID
            conversation_id: Conversation ID
            role: Message role (user, assistant, system, tool)
            content: Message content
        """
        await self.session.add_message(user_id, conversation_id, role, content)

    async def get_messages(
        self,
        user_id: str,
        conversation_id: str,
        limit: Optional[int] = None,
    ) -> list[dict[str, str]]:
        """
        Get session messages.
        
        Returns:
            List of messages in format: [{role: str, content: str}, ...]
        """
        return await self.session.get_messages(user_id, conversation_id, limit)

    # ─────────────────────────────────────────────────────────────────────────
    # Context Building
    # ─────────────────────────────────────────────────────────────────────────

    async def get_context(
        self,
        user_id: str,
        conversation_id: str,
        org_id: str,
        repo_id: Optional[str] = None,
        query: Optional[str] = None,
        session_limit: int = 10,
        ltm_limit: int = 3,
    ) -> str:
        """
        Build complete memory context for the agent.
        
        Combines:
        - Recent conversation history (session memory)
        - Relevant long-term facts (long-term memory)
        
        Args:
            user_id: User ID
            conversation_id: Conversation ID
            org_id: Organization ID
            repo_id: Optional repository filter
            query: Optional query for semantic memory retrieval
            session_limit: Max session messages to include
            ltm_limit: Max long-term memories to include
        
        Returns:
            Formatted context string for LLM
        """
        parts = []

        # Add long-term memories (show first for context priority)
        try:
            ltm_context = await self.long_term.get_formatted_context(
                user_id=user_id,
                query=query,
                repo_id=repo_id,
                limit=ltm_limit,
            )
            if ltm_context:
                parts.append(ltm_context)
        except Exception as e:
            logger.warning(f"Failed to retrieve long-term memory: {e}")

        # Add recent conversation
        try:
            session_context = await self.session.get_formatted_context(
                user_id=user_id,
                conversation_id=conversation_id,
                limit=session_limit,
            )
            if session_context:
                parts.append(session_context)
        except Exception as e:
            logger.warning(f"Failed to retrieve session memory: {e}")

        return "\n\n".join(parts) if parts else ""

    # ─────────────────────────────────────────────────────────────────────────
    # Memory Consolidation
    # ─────────────────────────────────────────────────────────────────────────

    async def consolidate(
        self,
        user_id: str,
        org_id: str,
        conversation_id: str,
        repo_id: Optional[str] = None,
    ) -> int:
        """
        Extract and store important facts from current conversation.
        
        Blocking version - waits for completion.
        Use consolidate_async() in request handlers.
        
        Returns:
            Number of facts extracted
        """
        messages = await self.session.get_messages(user_id, conversation_id)
        
        return await self.consolidator.consolidate(
            user_id=user_id,
            org_id=org_id,
            conversation_id=conversation_id,
            messages=messages,
            repo_id=repo_id,
        )

    async def consolidate_async(
        self,
        user_id: str,
        org_id: str,
        conversation_id: str,
        repo_id: Optional[str] = None,
    ) -> None:
        """
        Extract and store important facts asynchronously (fire-and-forget).
        
        Use this in request handlers to avoid blocking responses.
        """
        messages = await self.session.get_messages(user_id, conversation_id)
        
        await self.consolidator.consolidate_async(
            user_id=user_id,
            org_id=org_id,
            conversation_id=conversation_id,
            messages=messages,
            repo_id=repo_id,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Cleanup
    # ─────────────────────────────────────────────────────────────────────────

    async def clear_session(self, user_id: str, conversation_id: str) -> None:
        """
        Clear session memory for a conversation.
        Use when conversation is archived or deleted.
        """
        await self.session.clear(user_id, conversation_id)

    async def delete_memory(self, user_id: str, memory_id: str) -> bool:
        """
        Delete a specific long-term memory.
        
        Returns:
            True if deleted, False if not found
        """
        return await self.long_term.delete(user_id, memory_id)


# ─────────────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────────────

_memory_manager: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    """Get the singleton memory manager instance."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
