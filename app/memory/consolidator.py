"""
Memory consolidator — extracts important facts from conversations.

Analyzes conversation history to identify information worth remembering:
- User preferences and coding style
- Project-specific context and architecture
- Recurring bugs and solutions
- Important decisions and rationale

Implementation:
- Runs after each conversation turn (async, non-blocking)
- Uses LLM to extract facts from conversation
- Scores importance (0-1) for memory prioritization
- Stores in long-term memory for future retrieval
"""

from __future__ import annotations

import asyncio
from typing import Optional

from loguru import logger

from app.memory.long_term import LongTermMemory, MemoryEntry, get_long_term_memory
from app.ollama_client import OllamaClient, get_ollama_client

EXTRACTION_PROMPT = """Analyze this conversation and extract any important facts worth remembering for future conversations.

Look for:
1. User preferences (coding style, tools, frameworks)
2. Project context (architecture, patterns, tech stack)
3. Recurring issues (bugs, problems, solutions)
4. Important decisions (design choices, rationale)

Only extract facts that are:
- Specific and actionable
- Likely to be relevant in future conversations
- Not temporary or conversation-specific

Conversation:
{conversation_history}

Respond with a JSON array of facts. Each fact should have:
- content: The fact itself (1-2 sentences)
- type: One of [preference, fact, pattern, issue]
- importance: Float 0-1 (how useful is this?)

Example:
[
  {{"content": "User prefers TypeScript over JavaScript for type safety", "type": "preference", "importance": 0.8}},
  {{"content": "Project uses Repository pattern for all database access", "type": "pattern", "importance": 0.9}}
]

If there are no important facts to remember, return an empty array: []

Your response (JSON only):"""


class MemoryConsolidator:
    """
    Extracts and stores important facts from conversations.
    
    Design:
    - Runs asynchronously to avoid blocking responses
    - Uses LLM to identify important facts
    - Stores in long-term memory with importance scoring
    - Deduplicates similar facts (V2)
    """

    def __init__(
        self,
        ollama: Optional[OllamaClient] = None,
        long_term: Optional[LongTermMemory] = None,
        enabled: bool = True,
    ):
        self._ollama = ollama or get_ollama_client()
        self._long_term = long_term or get_long_term_memory()
        self.enabled = enabled

    async def consolidate(
        self,
        user_id: str,
        org_id: str,
        conversation_id: str,
        messages: list[dict[str, str]],
        repo_id: Optional[str] = None,
    ) -> int:
        """
        Analyze conversation and extract important facts.
        
        Args:
            user_id: User ID
            org_id: Organization ID
            conversation_id: Source conversation ID
            messages: List of messages [{role, content}, ...]
            repo_id: Optional repository context
        
        Returns:
            Number of facts extracted and stored
        """
        if not self.enabled:
            return 0

        if len(messages) < 4:  # Need meaningful conversation
            return 0

        try:
            # Format conversation history
            history = self._format_conversation(messages)
            
            # Call LLM to extract facts
            prompt = EXTRACTION_PROMPT.format(conversation_history=history)
            response = await self._ollama.chat(
                prompt=prompt,
                system_prompt="You are a fact extraction assistant. Return only valid JSON.",
                temperature=0.0,
            )
            
            # Parse extracted facts
            facts = self._parse_facts(response)
            
            if not facts:
                logger.debug(f"No facts extracted from conversation {conversation_id}")
                return 0
            
            # Store each fact in long-term memory
            stored_count = 0
            for fact in facts:
                entry = MemoryEntry(
                    user_id=user_id,
                    org_id=org_id,
                    repo_id=repo_id,
                    content=fact["content"],
                    memory_type=fact.get("type", "fact"),
                    importance=fact.get("importance", 0.5),
                    source_conversation_id=conversation_id,
                )
                
                await self._long_term.store(entry)
                stored_count += 1
            
            logger.info(f"Extracted {stored_count} facts from conversation {conversation_id}")
            return stored_count
            
        except Exception as e:
            logger.error(f"Memory consolidation failed: {e}")
            return 0

    def _format_conversation(self, messages: list[dict[str, str]]) -> str:
        """Format messages for LLM extraction."""
        lines = []
        for msg in messages:
            role = msg["role"].capitalize()
            content = msg["content"]
            # Truncate very long messages
            if len(content) > 1000:
                content = content[:1000] + "..."
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def _parse_facts(self, response: str) -> list[dict]:
        """Parse LLM response into fact dictionaries."""
        import json
        
        # Clean response
        cleaned = response.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1]) if len(lines) > 2 else cleaned
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
        
        try:
            parsed = json.loads(cleaned)
            
            if not isinstance(parsed, list):
                return []
            
            # Validate fact structure
            valid_facts = []
            for fact in parsed:
                if not isinstance(fact, dict):
                    continue
                
                content = fact.get("content")
                if not content or not isinstance(content, str):
                    continue
                
                # Ensure required fields
                fact_obj = {
                    "content": content,
                    "type": fact.get("type", "fact"),
                    "importance": float(fact.get("importance", 0.5)),
                }
                
                # Clamp importance to 0-1
                fact_obj["importance"] = max(0.0, min(1.0, fact_obj["importance"]))
                
                valid_facts.append(fact_obj)
            
            return valid_facts
            
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Failed to parse fact extraction response: {e}")
            return []

    async def consolidate_async(
        self,
        user_id: str,
        org_id: str,
        conversation_id: str,
        messages: list[dict[str, str]],
        repo_id: Optional[str] = None,
    ) -> None:
        """
        Consolidate memories asynchronously (fire-and-forget).
        
        Use this in request handlers to avoid blocking responses.
        """
        asyncio.create_task(
            self.consolidate(user_id, org_id, conversation_id, messages, repo_id)
        )


# Singleton instance
_consolidator: MemoryConsolidator | None = None


def get_consolidator() -> MemoryConsolidator:
    """Get the singleton memory consolidator instance."""
    global _consolidator
    if _consolidator is None:
        _consolidator = MemoryConsolidator()
    return _consolidator
