"""
OCR service — an independent stage, never embedded in parsers.

Triggers (decided by the pipeline, not here):
  - image uploads
  - PDFs whose text layer is empty/near-empty (scanned)

Providers plug in behind AbstractOcrProvider. The default NullOcrProvider
records that OCR was required but not performed — installing Tesseract and
switching the provider needs no other code changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class OcrResult:
    text: str = ""
    performed: bool = False
    provider: str = "none"
    detail: dict = field(default_factory=dict)


class AbstractOcrProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    async def extract_text(self, image_bytes: bytes, image_format: str) -> OcrResult: ...


class NullOcrProvider(AbstractOcrProvider):
    """No-op provider: flags the need for OCR without failing the pipeline."""

    name = "null"

    async def extract_text(self, image_bytes: bytes, image_format: str) -> OcrResult:
        return OcrResult(
            text="",
            performed=False,
            provider=self.name,
            detail={"reason": "no OCR provider configured"},
        )


class TesseractOcrProvider(AbstractOcrProvider):
    """
    Real OCR via pytesseract. Requires the Tesseract binary on the host.
    Not instantiated unless configured — importing pytesseract is deferred.
    """

    name = "tesseract"

    async def extract_text(self, image_bytes: bytes, image_format: str) -> OcrResult:
        import asyncio
        import io

        def _run() -> str:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore
            return pytesseract.image_to_string(Image.open(io.BytesIO(image_bytes)))

        text = await asyncio.to_thread(_run)
        return OcrResult(text=text.strip(), performed=True, provider=self.name)


class OcrService:
    def __init__(self, provider: AbstractOcrProvider | None = None) -> None:
        self._provider = provider or NullOcrProvider()

    @property
    def provider_name(self) -> str:
        return self._provider.name

    async def run(self, image_bytes: bytes, image_format: str) -> OcrResult:
        return await self._provider.extract_text(image_bytes, image_format)
