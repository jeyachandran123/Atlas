"""Composition root for document extraction.

The one place in the codebase where a provider is chosen and wired. Everything
above it (the router) and everything below it (the pipeline) is written against
``DocumentVLMPort``, which is why swapping NVIDIA for Ollama touches no file but
``.env``.

Assembly is deliberately explicit rather than magical: reading this function
tells an operator exactly what their configuration produced, which is the
question asked every time an extraction comes back looking wrong.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.adapters.document_vlm.registry import get_document_vlm
from app.config import Settings, get_settings
from app.document_platform.processing.ocr import (
    AbstractOcrProvider,
    NullOcrProvider,
    OcrService,
    TesseractOcrProvider,
)
from app.document_platform.vlm.payload import DocumentPayloadBuilder
from app.document_platform.vlm.pipeline import DocumentExtractionPipeline
from app.document_platform.vlm.prompts import InvoiceExtractionPromptProvider


def build_ocr_service(settings: Settings) -> OcrService:
    """The platform's existing OCR stage, with the configured provider.

    Reuses ``document_platform.processing.ocr`` rather than introducing a second
    OCR path — one platform, one answer to "what did we read off this page".
    """
    provider: AbstractOcrProvider = (
        TesseractOcrProvider()
        if settings.document_ocr_provider == "tesseract"
        else NullOcrProvider()
    )
    return OcrService(provider)


def build_prompt_provider(settings: Settings) -> InvoiceExtractionPromptProvider:
    return InvoiceExtractionPromptProvider(
        version=settings.document_vlm_prompt_version,
        max_text_chars=settings.document_context_max_chars,
        max_output_tokens=settings.document_vlm_max_output_tokens,
        temperature=settings.document_vlm_temperature,
    )


def build_extraction_pipeline(
    settings: Settings | None = None, *, vlm: Any = None
) -> DocumentExtractionPipeline:
    """Assemble the pipeline. ``vlm`` is injectable so tests never build a client."""
    cfg = settings or get_settings()
    return DocumentExtractionPipeline(
        vlm if vlm is not None else get_document_vlm(settings=cfg),
        payload_builder=DocumentPayloadBuilder(
            ocr=build_ocr_service(cfg),
            max_pages=cfg.document_vlm_max_pages,
            max_bytes=cfg.document_vlm_max_file_size_mb * 1024 * 1024,
        ),
        prompts=build_prompt_provider(cfg),
    )


@lru_cache
def _cached_pipeline() -> DocumentExtractionPipeline:
    return build_extraction_pipeline()


def get_extraction_pipeline() -> DocumentExtractionPipeline:
    """FastAPI dependency. Cached: the pipeline is stateless and the adapter
    holds only configuration, so rebuilding it per request would buy nothing.

    Overridable through ``app.dependency_overrides`` — which is how the API
    tests run the full route against a scripted provider with no network.
    """
    return _cached_pipeline()


def reset_extraction_pipeline_cache() -> None:
    """Drop the cached pipeline after a configuration change. For tests and
    for a hot reload."""
    _cached_pipeline.cache_clear()


__all__ = [
    "build_extraction_pipeline",
    "build_ocr_service",
    "build_prompt_provider",
    "get_extraction_pipeline",
    "reset_extraction_pipeline_cache",
]
