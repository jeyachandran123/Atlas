"""Builder contract. ContentModel in, bytes out — pure and deterministic.
Formats that embed timestamps (xlsx/docx/pdf) pin them to a fixed epoch so
identical content always produces identical bytes (auditability)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from app.document_platform.generation.content_model import ContentModel

# Fixed timestamp embedded in formats that require one — determinism over
# wall-clock vanity. Real creation time lives in the Generation Registry.
FIXED_BUILD_TIME = datetime(2000, 1, 1, tzinfo=timezone.utc)


class BuildError(Exception):
    """The builder could not render the model."""


class AbstractFileBuilder(ABC):
    format_name: str = "abstract"
    extension: str = ""
    content_type: str = "application/octet-stream"
    version: str = "1.0.0"
    features: frozenset[str] = frozenset()

    @abstractmethod
    def build(self, model: ContentModel) -> bytes:
        """Render the model. Must be deterministic and side-effect free."""
