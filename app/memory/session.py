"""
Session memory — short-term conversation history.

Stores the last N messages in Redis for fast access during conversation.
Uses a sliding window: old messages are automatically evicted.

Session memory is:
- Fast (Redis in-memory)
- Ephemeral (24-hour TTL)
- Per-conversation (isolated by conversation_id)
- Size-limited (last 20 messages)
"""

from __future__ import annotations

from typing import Optional

from app.redis_client import get_redis, get_session_messages, push_session_message

SESSION_WINDOW = 20  # Keep last 20 messages
SESSION_TTL = 86400  # 24 hours


class SessionMemory:
    """
    Manages short-term conversation memory in Redis.
    
    Design:
    - Stores last N messages per conversation
    - Messages are stored as {role, content, timestamp}
    - Automatically evicts old messages (LTRIM)
    - Expired after 24 hours of inactivity
    """

    def __init__(self, max_messages: int = SESSION_WINDOW, ttl_seconds: int = SESSION_TTL):
        self.max_messages = max_messages
        self.ttl_seconds = ttl_seconds

    async def add_message(
        self,
        user_id: str,
        conversation_id: str,
        role: str,
        content: str,
    ) -> None:
        """
        Add a message to the session window.
        
        Args:
            user_id: User ID for namespacing
            conversation_id: Conversation ID
            role: Message role (user, assistant, system, tool)
            content: Message content
        """
        await push_session_message(user_id, conversation_id, role, content)

    async def get_messages(
        self,
        user_id: str,
        conversation_id: str,
        limit: Optional[int] = None,
    ) -> list[dict[str, str]]:
        """
        Retrieve session messages in chronological order.
        
        Args:
            user_id: User ID
            conversation_id: Conversation ID
            limit: Optional limit on number of messages to return
        
        Returns:
            List of messages in format: [{role: str, content: str}, ...]
        """
        messages = await get_session_messages(user_id, conversation_id)
        
        if limit and limit < len(messages):
            # Return most recent N messages
            return messages[-limit:]
        
        return messages

    async def clear(self, user_id: str, conversation_id: str) -> None:
        """
        Clear all session messages for a conversation.
        Used when conversation is archived or deleted.
        """
        key = f"session:{user_id}:{conversation_id}"
        r = get_redis()
        await r.delete(key)

    async def get_formatted_context(
        self,
        user_id: str,
        conversation_id: str,
        limit: Optional[int] = None,
    ) -> str:
        """
        Get session messages formatted for LLM context.
        
        Returns:
            Formatted string like:
            ```
            Previous conversation:
            User: Hello
            Assistant: Hi! How can I help?
            User: Show me the code
            ```
        """
        messages = await self.get_messages(user_id, conversation_id, limit)
        
        if not messages:
            return ""
        
        formatted_lines = ["Previous conversation:"]
        for msg in messages:
            role = msg["role"].capitalize()
            content = msg["content"]
            # Truncate very long messages for context efficiency
            if len(content) > 500:
                content = content[:500] + "..."
            formatted_lines.append(f"{role}: {content}")
        
        return "\n".join(formatted_lines)


# Singleton instance
_session_memory: SessionMemory | None = None


def get_session_memory() -> SessionMemory:
    """Get the singleton session memory instance."""
    global _session_memory
    if _session_memory is None:
        _session_memory = SessionMemory()
    return _session_memory
