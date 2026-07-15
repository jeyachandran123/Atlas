"""
Vision Intelligence Module.

Integrates multimodal (image) capabilities into the Atlas Conversation Intelligence Engine.
Vision is NOT a separate application — it extends the existing pipeline.
"""

from app.vision.schemas import ImageAttachment, ImageAttachmentOut, VisionIntent
from app.vision.service import VisionService, get_vision_service

__all__ = [
    "ImageAttachment",
    "ImageAttachmentOut",
    "VisionIntent",
    "VisionService",
    "get_vision_service",
]
