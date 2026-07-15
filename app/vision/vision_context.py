"""
Vision Context — manages image references within a conversation.

Ensures follow-up questions can reference previously uploaded images
without re-uploading. Stores image metadata per conversation in Redis.
"""
from __future__ import annotations

import json
from typing import Optional

from loguru import logger

from app.vision.schemas import ImageAttachment


class VisionContext:
    """
    Tracks images uploaded in a conversation so follow-up questions
    can reference them without re-upload.
    """

    def __init__(self) -> None:
        # In-memory fallback: conversation_id → list of ImageAttachment dicts
        self._cache: dict[str, list[dict]] = {}

    async def add_images(
        self, conversation_id: str, attachments: list[ImageAttachment]
    ) -> None:
        """Register images for a conversation."""
        existing = self._cache.get(conversation_id, [])
        for att in attachments:
            existing.append(att.model_dump(mode="json"))
        self._cache[conversation_id] = existing

        # Also persist to Redis if available
        try:
            from app.redis_client import get_redis
            r = get_redis()
            key = f"vision:images:{conversation_id}"
            await r.set(key, json.dumps(existing), ex=86400)  # 24h TTL
        except Exception as e:
            logger.debug(f"Redis vision context save failed (using memory): {e}")

    async def get_images(self, conversation_id: str) -> list[ImageAttachment]:
        """Get all images uploaded in this conversation."""
        # Try Redis first
        try:
            from app.redis_client import get_redis
            r = get_redis()
            key = f"vision:images:{conversation_id}"
            data = await r.get(key)
            if data:
                items = json.loads(data)
                self._cache[conversation_id] = items
                return [ImageAttachment(**item) for item in items]
        except Exception:
            pass

        # Fallback to memory
        items = self._cache.get(conversation_id, [])
        return [ImageAttachment(**item) for item in items]

    async def get_latest_images(
        self, conversation_id: str, limit: int = 5
    ) -> list[ImageAttachment]:
        """Get the most recent images in the conversation."""
        all_images = await self.get_images(conversation_id)
        return all_images[-limit:]

    async def has_images(self, conversation_id: str) -> bool:
        """Check if conversation has any uploaded images."""
        images = await self.get_images(conversation_id)
        return len(images) > 0


# Singleton
_context: VisionContext | None = None


def get_vision_context() -> VisionContext:
    global _context
    if _context is None:
        _context = VisionContext()
    return _context
