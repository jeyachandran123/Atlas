"""Unauthenticated invoice extraction — **development only**.

The real endpoint (`/api/v1/document/extract-invoice`) requires a JWT or an
X-API-Key, which is right for an ERP integration and a nuisance for a five-minute
"does this actually work" check from a demo page.

This route is the same pipeline with the auth dependency removed, and it is
mounted **only when ``APP_DEBUG`` is true** — see ``app.main``. In production the
module is imported and the router simply never mounts, so there is no
unauthenticated document sink to forget about.

Delete this file when the check is done; nothing else imports it.
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse

from app.api.v1.document_extraction.dependencies import get_extraction_pipeline
from app.document_platform.vlm.errors import (
    DocumentExtractionError,
    DocumentVLMError,
    InvoiceSchemaError,
)
from app.document_platform.vlm.pipeline import DocumentExtractionPipeline

router = APIRouter(prefix="/dev", tags=["Document Extraction (dev)"])


@router.post("/extract-invoice", summary="Extract an invoice — no auth, debug builds only")
async def dev_extract_invoice(
    file: UploadFile = File(...),
    pipeline: DocumentExtractionPipeline = Depends(get_extraction_pipeline),
):
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    content = await file.read()

    try:
        outcome = await pipeline.extract_invoice(
            filename=file.filename or "upload",
            content=content,
            declared_mime=file.content_type,
            request_id=request_id,
        )
    except (InvoiceSchemaError, DocumentExtractionError, DocumentVLMError) as exc:
        # Same envelope as the real endpoint, built plainly: this is a probe, and
        # a probe that reshapes errors would hide the thing being probed.
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "success": False,
                "provider": getattr(exc, "provider", "") or pipeline.provider_name,
                "model": getattr(exc, "model", "") or pipeline.model_name,
                "processingTime": round((time.perf_counter() - started) * 1000, 2),
                "requestId": request_id,
                "error": {
                    "code": getattr(exc, "code", "error"),
                    "message": exc.message,
                    "retryable": getattr(exc, "retryable", False),
                    "violations": list(getattr(exc, "violations", ())),
                    # The whole point of a probe: when the model says something
                    # unusable, show what it said and why it stopped. The real
                    # endpoint keeps this out of the wire contract; here it is
                    # the diagnosis.
                    "rawExcerpt": getattr(exc, "raw_excerpt", ""),
                    "context": {
                        key: value
                        for key, value in getattr(exc, "context", {}).items()
                        if key != "raw_excerpt"
                    },
                },
            },
        )

    return {
        "success": True,
        "provider": outcome.provider,
        "model": outcome.model,
        "processingTime": outcome.processing_time_ms,
        "data": outcome.data,
        "requestId": outcome.request_id,
        "promptVersion": outcome.prompt_version,
        "schemaVersion": outcome.schema_version,
        "warnings": list(outcome.warnings),
        "usage": outcome.usage.as_dict(),
        "retryCount": outcome.retry_count,
        "jsonRepaired": outcome.json_repaired,
        "stages": dict(outcome.stages),
        "document": dict(outcome.document),
    }


@router.get("/vlm/health", summary="Provider health — no auth, debug builds only")
async def dev_vlm_health(
    pipeline: DocumentExtractionPipeline = Depends(get_extraction_pipeline),
):
    health = await pipeline.health()
    return JSONResponse(
        status_code=200 if health.healthy else 503, content=health.as_dict()
    )


__all__ = ["router"]
