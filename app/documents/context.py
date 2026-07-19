"""
Document Context — tracks documents uploaded within a conversation.

Ensures follow-up questions can reference previously uploaded documents
without re-upload. Metadata is stored per conversation in Redis (24h TTL)
with an in-memory fallback; extracted text stays on disk (see storage.py).

Mirrors app/vision/vision_context.py.
"""
from __future__ import annotations

import json

from loguru import logger

from app.documents.schemas import DocumentAttachment


class DocumentContext:
    """Tracks documents uploaded in a conversation for follow-up Q&A."""

    def __init__(self) -> None:
        # In-memory fallback: conversation_id → list of DocumentAttachment dicts
        self._cache: dict[str, list[dict]] = {}

    async def add_documents(
        self, conversation_id: str, attachments: list[DocumentAttachment]
    ) -> None:
        """Register documents for a conversation."""
        existing = self._cache.get(conversation_id, [])
        known_ids = {item.get("id") for item in existing}
        for att in attachments:
            if att.id not in known_ids:
                existing.append(att.model_dump(mode="json"))
        self._cache[conversation_id] = existing

        try:
            from app.redis_client import get_redis
            r = get_redis()
            key = f"docs:context:{conversation_id}"
            await r.set(key, json.dumps(existing), ex=86400)  # 24h TTL
        except Exception as e:
            logger.debug(f"Redis document context save failed (using memory): {e}")

    async def get_documents(self, conversation_id: str) -> list[DocumentAttachment]:
        """Get all documents uploaded in this conversation."""
        try:
            from app.redis_client import get_redis
            r = get_redis()
            key = f"docs:context:{conversation_id}"
            data = await r.get(key)
            if data:
                items = json.loads(data)
                self._cache[conversation_id] = items
                return [DocumentAttachment(**item) for item in items]
        except Exception:
            pass

        items = self._cache.get(conversation_id, [])
        return [DocumentAttachment(**item) for item in items]

    async def get_latest_documents(
        self, conversation_id: str, limit: int = 5
    ) -> list[DocumentAttachment]:
        """Get the most recent documents in the conversation."""
        all_docs = await self.get_documents(conversation_id)
        return all_docs[-limit:]

    async def has_documents(self, conversation_id: str) -> bool:
        docs = await self.get_documents(conversation_id)
        return len(docs) > 0


# Singleton
_context: DocumentContext | None = None


def get_document_context() -> DocumentContext:
    global _context
    if _context is None:
        _context = DocumentContext()
    return _context
