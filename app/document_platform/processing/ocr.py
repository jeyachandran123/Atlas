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


# ── Vision-model description ─────────────────────────────────────────────────

IMAGE_DESCRIPTION_PROMPT_ID = "image_description"
IMAGE_DESCRIPTION_PROMPT_VERSION = "1.0.0"

_DESCRIBE_SYSTEM = (
    "You describe images so that they can be found by search later. "
    "Reply with JSON and nothing else."
)

_DESCRIBE_USER = (
    "Describe this image in full: what it shows, what is happening in it, and "
    "anything about it a person might later search for. Then transcribe every "
    "piece of text visible in the image, verbatim, in reading order.\n"
    'Reply with exactly this JSON object: {"description": "...", "text": "..."}\n'
    'Use an empty string for "text" if the image contains no readable text. '
    "Never describe anything you cannot actually see."
)

_MAX_IMAGE_BYTES = 130_000
"""Ceiling on the bytes handed to the model, before base64.

Endpoints cap the size of an inline image, and base64 inflates what is sent by
four thirds — so 130KB of pixels arrives as roughly 173KB on the wire. A
screenshot off a modern display is five or six times that, and an image over
the cap is not degraded gracefully: it is rejected, or dropped before sending,
and the document ends up indexed with nothing in it. Shrinking first is what
makes a real screenshot work rather than a small test one.
"""

_MAX_EDGE = 1600
"""Longest side kept, in pixels. Past this, resolution buys nothing a model
reads better and costs latency on every upload."""


def _fit_for_model(content: bytes) -> tuple[bytes, str]:
    """Re-encode an image down to something an endpoint will accept.

    Returns the original bytes unchanged if Pillow is unavailable or the image
    cannot be decoded — a possibly-oversized attempt the provider may reject is
    still better than refusing to try, and the caller treats a provider error
    as "not performed" rather than as a failure of the upload.
    """
    try:
        import io

        from PIL import Image  # type: ignore
    except ImportError:
        return content, "image/png"

    try:
        image = Image.open(io.BytesIO(content))
        image.load()
    except Exception:  # noqa: BLE001 - an undecodable image is not an error here
        return content, "image/png"

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    if max(image.size) > _MAX_EDGE:
        ratio = _MAX_EDGE / max(image.size)
        image = image.resize(
            (max(1, int(image.width * ratio)), max(1, int(image.height * ratio))),
            Image.LANCZOS,
        )

    # Quality is stepped down rather than guessed at: text in a screenshot is
    # the thing most worth preserving and the first thing JPEG destroys, so the
    # highest setting that fits is the one to send.
    encoded = content
    for quality in (85, 70, 55, 40):
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        encoded = buffer.getvalue()
        if len(encoded) <= _MAX_IMAGE_BYTES:
            break
    return encoded, "image/jpeg"


class VlmOcrProvider(AbstractOcrProvider):
    """Turn an image into indexable text using the configured vision model.

    This is OCR's slot in the pipeline, filled by something that reads more
    than characters. The stage exists to answer one question — "what text does
    this image contribute to the knowledge base?" — and for a photograph, a
    chart or a screenshot the honest answer includes what the image *shows*,
    not only the glyphs in it. Without this the pipeline records an image node
    holding the filename, produces no chunks at all, and still reports the
    document ready: every question about it is then truthfully refused for want
    of any source, which reads to the user as the assistant ignoring a file
    they can see in the sidebar.

    The model is injected, never constructed here. Which vision provider
    answers is a deployment decision made once at the composition root; this
    class knows only that something implements the port.
    """

    name = "vlm"

    def __init__(self, vlm: object, *, max_output_tokens: int = 900) -> None:
        self._vlm = vlm
        self._max_output_tokens = max_output_tokens

    async def extract_text(self, image_bytes: bytes, image_format: str) -> OcrResult:
        from app.document_platform.vlm.errors import (
            DocumentVLMError,
            DocumentVLMInvalidResponseError,
        )
        from app.document_platform.vlm.ports import (
            DocumentImage,
            DocumentPayload,
            ExtractionPrompt,
            VLMExtractionRequest,
        )

        if not image_bytes:
            return OcrResult(provider=self.name, detail={"reason": "empty image"})

        content, media_type = _fit_for_model(image_bytes)
        request = VLMExtractionRequest(
            payload=DocumentPayload(
                images=(DocumentImage(data=content, media_type=media_type, page=1),),
                media_type=media_type,
                page_count=1,
            ),
            prompt=ExtractionPrompt(
                system=_DESCRIBE_SYSTEM,
                user=_DESCRIBE_USER,
                prompt_id=IMAGE_DESCRIPTION_PROMPT_ID,
                version=IMAGE_DESCRIPTION_PROMPT_VERSION,
                max_output_tokens=self._max_output_tokens,
            ),
        )

        try:
            result = await self._vlm.extract_document(request)
        except DocumentVLMInvalidResponseError as e:
            # The model answered in prose instead of JSON. Prose describing an
            # image is exactly what this stage wanted; the JSON was only ever a
            # convenience for splitting description from transcription.
            text = (e.raw_excerpt or "").strip()
            if not text:
                return OcrResult(
                    provider=self.name, detail={"reason": "unusable response"}
                )
            return OcrResult(
                text=text, performed=True, provider=self.name,
                detail={"format": "prose"},
            )
        except DocumentVLMError as e:
            # A vision model that cannot be reached must not fail the upload.
            # The document still parses, still stores and still lists; it is
            # this one stage that produced nothing, and recording that is what
            # lets the image be described later without re-uploading it.
            return OcrResult(
                provider=self.name,
                detail={"reason": "vlm unavailable", "error": e.__class__.__name__},
            )
        except Exception as e:  # noqa: BLE001 - same reasoning, wider net
            return OcrResult(
                provider=self.name,
                detail={"reason": "vlm call failed", "error": e.__class__.__name__},
            )

        return OcrResult(
            text=_readable(result.structured, result.raw_text),
            performed=True,
            provider=self.name,
            detail={"model": result.model, "latency_ms": int(result.latency_ms)},
        )


def _readable(structured: object, raw_text: str) -> str:
    """The model's answer as one block of prose for the index.

    Description and transcription are joined rather than kept apart because the
    consumer is a chunker: it sees text, not fields, and two labelled
    paragraphs retrieve better than a JSON document nobody will parse again.
    """
    if not isinstance(structured, dict):
        return (raw_text or "").strip()

    description = str(structured.get("description") or "").strip()
    text = str(structured.get("text") or "").strip()
    parts = [description] if description else []
    if text:
        parts.append(f"Text shown in the image:\n{text}")
    return "\n\n".join(parts) or (raw_text or "").strip()
