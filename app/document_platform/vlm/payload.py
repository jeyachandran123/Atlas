"""Turn an upload into something a VLM can be asked about.

This is the stage between "bytes arrived over HTTP" and "a model was asked a
question", and it is where the platform's *existing* OCR implementation is
reused rather than reinvented: ``OcrService`` from
``document_platform.processing.ocr`` is injected here, with whatever provider a
deployment configured, and this module never learns which one.

What it produces is a ``DocumentPayload`` — pixels, text, or both — and what it
refuses to produce is a payload with neither. A VLM handed an empty document
does not return an empty answer; it returns a fluent, plausible, entirely
invented invoice. Catching that here, with a typed error naming the real
problem, is worth more than any downstream validation.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from loguru import logger

from app.document_platform.constants import MAGIC_SIGNATURES
from app.document_platform.processing.ocr import OcrService
from app.document_platform.vlm.errors import (
    DocumentTooLargeError,
    EmptyDocumentError,
    UnsupportedDocumentError,
)
from app.document_platform.vlm.ports import DocumentImage, DocumentPayload

#: What can be put in front of a VLM: a PDF, or an image of a document.
#: Deliberately narrower than the platform's upload allowlist — a .docx has a
#: text layer and no pixels, and belongs in the text pipeline, not this one.
IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}

SUPPORTED_EXTENSIONS = frozenset({".pdf", *IMAGE_MEDIA_TYPES})

#: Below this many characters per page, a PDF's text layer is decoration on a
#: scan rather than the document's actual text. Matches the threshold the
#: existing PDF parser uses to flag ``needs_ocr`` — one platform, one answer to
#: "is this scanned".
_SCANNED_CHARS_PER_PAGE = 50


@dataclass(frozen=True, slots=True)
class PayloadBuildReport:
    """How the payload was assembled — provenance for the response envelope."""

    payload: DocumentPayload
    extension: str
    ocr_performed: bool
    ocr_provider: str
    notes: tuple[str, ...] = ()


class DocumentPayloadBuilder:
    """Uploads in, ``DocumentPayload`` out. Knows nothing about any provider."""

    def __init__(
        self,
        *,
        ocr: OcrService | None = None,
        max_pages: int = 8,
        max_bytes: int = 20 * 1024 * 1024,
    ) -> None:
        self._ocr = ocr or OcrService()
        self._max_pages = max(1, max_pages)
        self._max_bytes = max_bytes

    async def build(
        self,
        *,
        filename: str,
        content: bytes,
        declared_mime: str | None = None,
    ) -> PayloadBuildReport:
        if not content:
            raise EmptyDocumentError(
                f"'{filename or 'upload'}' contains no bytes", filename=filename
            )
        if len(content) > self._max_bytes:
            raise DocumentTooLargeError(
                f"document is {len(content) / 1_048_576:.1f} MB, above the "
                f"{self._max_bytes / 1_048_576:.0f} MB limit",
                size_bytes=len(content),
                limit_bytes=self._max_bytes,
            )

        extension = self._extension(filename, content, declared_mime)

        if extension == ".pdf":
            return await self._from_pdf(filename, content)
        return await self._from_image(filename, content, extension)

    # ── type resolution ──────────────────────────────────────────────────────

    def _extension(self, filename: str, content: bytes, declared_mime: str | None) -> str:
        """Decide the type from the bytes first, the name second.

        Content wins because a client's filename and Content-Type are both
        things a client chose, and neither survives contact with a real ERP
        integration unchanged.
        """
        if content.startswith(b"%PDF"):
            return ".pdf"
        for ext, signatures in MAGIC_SIGNATURES.items():
            if ext in IMAGE_MEDIA_TYPES and any(content.startswith(s) for s in signatures):
                return ext

        name = (filename or "").lower()
        for ext in SUPPORTED_EXTENSIONS:
            if name.endswith(ext):
                return ext

        mime = (declared_mime or "").lower().split(";")[0].strip()
        if mime == "application/pdf":
            return ".pdf"
        for ext, media_type in IMAGE_MEDIA_TYPES.items():
            if mime == media_type:
                return ext

        raise UnsupportedDocumentError(
            f"'{filename or 'upload'}' is not a document this pipeline can read; "
            f"supported types are {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
            filename=filename,
            declared_mime=declared_mime,
        )

    # ── images ───────────────────────────────────────────────────────────────

    async def _from_image(
        self, filename: str, content: bytes, extension: str
    ) -> PayloadBuildReport:
        media_type = IMAGE_MEDIA_TYPES[extension]
        image = DocumentImage(data=content, media_type=media_type, page=1)

        text, performed = await self._run_ocr(content, extension.lstrip("."))

        return PayloadBuildReport(
            payload=DocumentPayload(
                images=(image,),
                ocr_text=text,
                filename=filename,
                media_type=media_type,
                page_count=1,
                text_source="ocr" if performed and text else "none",
            ),
            extension=extension,
            ocr_performed=performed,
            ocr_provider=self._ocr.provider_name,
        )

    # ── PDFs ─────────────────────────────────────────────────────────────────

    async def _from_pdf(self, filename: str, content: bytes) -> PayloadBuildReport:
        """Text layer first, pixels second, OCR only if the first two disagree
        about whether there is anything to read.

        A born-digital PDF's text layer is exact and free; extracting it beats
        asking a model to read a picture of it. A scanned PDF has no text layer,
        and its page images are the only thing there is. Most real invoice
        streams contain both, which is why this decides per document rather than
        per deployment.
        """
        text, page_count = await asyncio.to_thread(self._pdf_text, content)
        images = await asyncio.to_thread(self._pdf_images, content, self._max_pages)

        notes: list[str] = []
        performed = False
        text_source = "pdf_text_layer" if text.strip() else "none"

        scanned = len(text.strip()) < _SCANNED_CHARS_PER_PAGE * max(1, page_count)
        if scanned and images:
            notes.append("pdf text layer is empty or near-empty; treated as scanned")
            ocr_text, performed = await self._run_ocr_many(images)
            if ocr_text.strip():
                text = ocr_text if not text.strip() else f"{text}\n\n{ocr_text}"
                text_source = "ocr"

        if not images and not text.strip():
            raise EmptyDocumentError(
                f"'{filename or 'document.pdf'}' yielded neither text nor page "
                f"images; it may be encrypted, corrupt, or a scan this build "
                f"cannot rasterise",
                filename=filename,
                page_count=page_count,
            )

        if page_count > self._max_pages and images:
            notes.append(
                f"document has {page_count} pages; the first {len(images)} "
                f"images were sent to the model"
            )

        return PayloadBuildReport(
            payload=DocumentPayload(
                images=tuple(images),
                ocr_text=text,
                filename=filename,
                media_type="application/pdf",
                page_count=page_count,
                text_source=text_source,
            ),
            extension=".pdf",
            ocr_performed=performed,
            ocr_provider=self._ocr.provider_name,
            notes=tuple(notes),
        )

    @staticmethod
    def _pdf_text(content: bytes) -> tuple[str, int]:
        """Extract the embedded text layer. Never raises — an unreadable PDF
        yields no text, and the caller decides what that means."""
        import io

        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            pages: list[str] = []
            for number, page in enumerate(reader.pages, start=1):
                try:
                    extracted = page.extract_text() or ""
                except Exception as exc:  # noqa: BLE001 - one bad page is not a bad file
                    logger.debug(f"PDF page {number} text extraction failed: {exc}")
                    extracted = ""
                if extracted.strip():
                    pages.append(f"[page {number}]\n{extracted.strip()}")
            return "\n\n".join(pages), len(reader.pages)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"PDF text extraction failed: {type(exc).__name__}: {exc}")
            return "", 0

    @staticmethod
    def _pdf_images(content: bytes, limit: int) -> list[DocumentImage]:
        """Pull embedded page images out of a PDF, best effort.

        Embedded images rather than rendered pages: rasterising a PDF needs a
        renderer this deployment does not ship, and a scanned invoice is
        virtually always *one full-page image per page*, which is exactly what
        this recovers. A born-digital PDF returns logos and nothing else — which
        is why the text layer, not this, is authoritative when both exist.
        """
        import io

        collected: list[DocumentImage] = []
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(content))
            for number, page in enumerate(reader.pages, start=1):
                if len(collected) >= limit:
                    break
                try:
                    embedded = list(page.images)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(f"PDF page {number} image extraction failed: {exc}")
                    continue
                for item in embedded:
                    if len(collected) >= limit:
                        break
                    data = getattr(item, "data", b"")
                    name = str(getattr(item, "name", "") or "")
                    media_type = _media_type_for(name, data)
                    if not data or media_type is None:
                        continue
                    collected.append(
                        DocumentImage(data=data, media_type=media_type, page=number)
                    )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"PDF image extraction failed: {type(exc).__name__}: {exc}")
        return collected

    # ── OCR ──────────────────────────────────────────────────────────────────

    async def _run_ocr(self, content: bytes, image_format: str) -> tuple[str, bool]:
        """Run the platform's OCR stage. A failure is degradation, not an error.

        With images in the payload the model still has the pixels, so a broken
        OCR provider costs accuracy rather than the whole extraction.
        """
        try:
            result = await self._ocr.run(content, image_format)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"OCR stage failed ({type(exc).__name__}); continuing without text")
            return "", False
        return (result.text or "").strip(), bool(result.performed)

    async def _run_ocr_many(self, images: list[DocumentImage]) -> tuple[str, bool]:
        chunks: list[str] = []
        performed = False
        for image in images:
            text, ran = await self._run_ocr(
                image.data, image.media_type.split("/", 1)[-1]
            )
            performed = performed or ran
            if text:
                chunks.append(
                    f"[page {image.page}]\n{text}" if image.page else text
                )
        return "\n\n".join(chunks), performed


def _media_type_for(name: str, data: bytes) -> str | None:
    """Media type of an embedded image, from its name or its magic bytes."""
    lowered = name.lower()
    for extension, media_type in IMAGE_MEDIA_TYPES.items():
        if lowered.endswith(extension):
            return media_type
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return "image/webp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    return None


__all__ = [
    "IMAGE_MEDIA_TYPES",
    "SUPPORTED_EXTENSIONS",
    "DocumentPayloadBuilder",
    "PayloadBuildReport",
]
