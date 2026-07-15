"""
Vision schemas — data structures for image-augmented conversations.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class VisionIntent(str, Enum):
    """Vision-specific intent values detected when images are present."""
    IMAGE_DESCRIPTION = "image_description"
    OCR = "ocr"
    OBJECT_DETECTION = "object_detection"
    UI_ANALYSIS = "ui_analysis"
    CODE_SCREENSHOT = "code_screenshot"
    DIAGRAM_ANALYSIS = "diagram_analysis"
    ERROR_SCREENSHOT = "error_screenshot"
    CHART_ANALYSIS = "chart_analysis"
    DOCUMENT_ANALYSIS = "document_analysis"
    GENERAL_VISION = "general_vision"


class ImageAttachment(BaseModel):
    """Metadata for an uploaded image, stored alongside a message."""
    id: str
    conversation_id: str
    message_id: Optional[str] = None
    filename: str
    mime_type: str
    size_bytes: int
    storage_path: str
    image_hash: str  # SHA256
    width: Optional[int] = None
    height: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ImageAttachmentOut(BaseModel):
    """Public-facing image metadata returned to the frontend."""
    id: str
    filename: str
    mime_type: str
    size_bytes: int
    width: Optional[int] = None
    height: Optional[int] = None
    url: str = ""  # served path
    created_at: datetime
