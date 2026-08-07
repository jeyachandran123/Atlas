"""Document Extraction REST API.

    POST /api/v1/document/extract-invoice   → invoice JSON from a PDF or image
    GET  /api/v1/document/vlm/health        → can the bound provider serve?
    GET  /api/v1/document/vlm/provider      → what is bound, and how

One endpoint is the entire ERP integration surface: post a file, receive
structured JSON. Nothing in the contract names a model vendor, so the day this
deployment changes which one answers, no ERP changes, no client is redeployed,
and no integration is renegotiated.

The controller does HTTP and nothing else: read the upload, call the pipeline,
map typed errors onto status codes. Every decision worth making happens in the
platform, where it can be tested without a web server.
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from fastapi.responses import JSONResponse

from app.api.v1.document_extraction.dependencies import get_extraction_pipeline
from app.api.v1.document_extraction.schemas import (
    DocumentInfoOut,
    ExtractionErrorDetail,
    ExtractionErrorResponse,
    ExtractionResponse,
    ProviderHealthOut,
    ProviderInfoOut,
    TokenUsageOut,
)
from app.auth import get_current_user
from app.config import get_settings
from app.db.models import User
from app.document_platform.vlm.errors import (
    DocumentExtractionError,
    DocumentVLMError,
    InvoiceSchemaError,
)
from app.document_platform.vlm.pipeline import DocumentExtractionPipeline
from app.document_platform.vlm.ports import DOCUMENT_VLM_PORT_VERSION

router = APIRouter(prefix="/document", tags=["Document Extraction"])


@router.post(
    "/extract-invoice",
    response_model=ExtractionResponse,
    responses={
        413: {"model": ExtractionErrorResponse},
        415: {"model": ExtractionErrorResponse},
        422: {"model": ExtractionErrorResponse},
        429: {"model": ExtractionErrorResponse},
        502: {"model": ExtractionErrorResponse},
        503: {"model": ExtractionErrorResponse},
        504: {"model": ExtractionErrorResponse},
    },
    summary="Extract structured invoice data from a PDF or image",
)
async def extract_invoice(
    file: UploadFile = File(..., description="PDF or image of an invoice"),
    prompt_version: str | None = Form(
        None,
        description="Pin a prompt version. Omit to use the deployment's configured one.",
    ),
    current_user: User = Depends(get_current_user),
    pipeline: DocumentExtractionPipeline = Depends(get_extraction_pipeline),
):
    """Run the extraction pipeline over one uploaded document.

    OCR, prompt selection, the model call, JSON recovery and schema validation
    all happen behind this call. A failure at any stage returns a typed error
    with a code the caller can branch on — never a 200 carrying an empty or
    invented invoice.
    """
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    content = await file.read()

    try:
        outcome = await pipeline.extract_invoice(
            filename=file.filename or "upload",
            content=content,
            declared_mime=file.content_type,
            request_id=request_id,
            prompt_version=prompt_version or None,
        )
    except InvoiceSchemaError as exc:
        return _error_response(
            status_code=exc.http_status,
            code=exc.code,
            message=exc.message,
            request_id=request_id,
            provider=str(exc.context.get("provider", "")),
            model=str(exc.context.get("model", "")),
            violations=list(exc.violations),
            elapsed=started,
        )
    except DocumentExtractionError as exc:
        return _error_response(
            status_code=exc.http_status,
            code=exc.code,
            message=exc.message,
            request_id=request_id,
            elapsed=started,
        )
    except DocumentVLMError as exc:
        return _error_response(
            status_code=exc.http_status,
            code=exc.code,
            message=exc.message,
            request_id=request_id,
            provider=exc.provider,
            model=exc.model,
            retryable=exc.retryable,
            elapsed=started,
            retry_after=exc.retry_after_seconds,
        )

    return ExtractionResponse(
        success=True,
        provider=outcome.provider,
        model=outcome.model,
        processing_time=outcome.processing_time_ms,
        data=outcome.data,
        request_id=outcome.request_id,
        prompt_version=outcome.prompt_version,
        schema_version=outcome.schema_version,
        warnings=list(outcome.warnings),
        usage=TokenUsageOut(**outcome.usage.as_dict()),
        retry_count=outcome.retry_count,
        json_repaired=outcome.json_repaired,
        stages=dict(outcome.stages),
        document=DocumentInfoOut(**outcome.document),
    )


@router.get(
    "/vlm/health",
    response_model=ProviderHealthOut,
    summary="Health of the bound VLM provider",
)
async def vlm_health(
    response: Response,
    current_user: User = Depends(get_current_user),
    pipeline: DocumentExtractionPipeline = Depends(get_extraction_pipeline),
):
    """Probe the provider. Returns 503 when unhealthy, with the reason.

    A 200 body carrying ``healthy: false`` would be invisible to every uptime
    monitor ever built, so the status code carries the verdict too.
    """
    health = await pipeline.health()
    if not health.healthy:
        response.status_code = 503
    return ProviderHealthOut(
        healthy=health.healthy,
        provider=health.provider,
        model=health.model,
        latency_ms=round(health.latency_ms, 2),
        detail=dict(health.detail),
        error=health.error,
    )


@router.get(
    "/vlm/provider",
    response_model=ProviderInfoOut,
    summary="Which provider is bound, and with what limits",
)
async def vlm_provider(
    current_user: User = Depends(get_current_user),
    pipeline: DocumentExtractionPipeline = Depends(get_extraction_pipeline),
):
    """Report the effective configuration — without a single credential.

    Answers "which model produced this extraction" and "why is this provider
    refusing me" from one place, which is otherwise a question that costs a
    deploy to answer.
    """
    from app.adapters.document_vlm.registry import describe_document_vlm

    cfg = get_settings()
    described = describe_document_vlm(cfg)
    prompts = pipeline.prompts

    return ProviderInfoOut(
        provider=pipeline.provider_name,
        model=pipeline.model_name,
        available_providers=list(described.get("available_providers", [])),
        base_url=str(described.get("base_url", "")),
        api_key_configured=bool(described.get("api_key_configured", False)),
        prompt_id=getattr(prompts, "prompt_id", ""),
        prompt_version=getattr(prompts, "version", ""),
        available_prompt_versions=list(getattr(prompts, "versions", lambda: ())()),
        schema_version=getattr(prompts, "schema_version", ""),
        port_version=DOCUMENT_VLM_PORT_VERSION,
        limits={
            "max_file_size_mb": cfg.document_vlm_max_file_size_mb,
            "max_pages": cfg.document_vlm_max_pages,
            "max_output_tokens": cfg.document_vlm_max_output_tokens,
            "timeout_seconds": cfg.document_vlm_timeout_seconds,
            "max_retries": cfg.document_vlm_max_retries,
        },
    )


# ── error mapping ────────────────────────────────────────────────────────────


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str,
    elapsed: float,
    provider: str = "",
    model: str = "",
    retryable: bool = False,
    violations: list[str] | None = None,
    retry_after: float | None = None,
) -> JSONResponse:
    """One failure envelope, built one way.

    ``Retry-After`` is set from the provider's own signal when there was one:
    a client that is told to back off for 12 seconds and instead retries
    immediately turns one rate limit into a sustained one.
    """
    body = ExtractionErrorResponse(
        success=False,
        provider=provider,
        model=model,
        processing_time=round((time.perf_counter() - elapsed) * 1000.0, 2),
        request_id=request_id,
        error=ExtractionErrorDetail(
            code=code,
            message=message,
            retryable=retryable,
            violations=violations or [],
        ),
    )
    headers = {"Retry-After": str(int(retry_after))} if retry_after else None
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(by_alias=True),
        headers=headers,
    )


__all__ = ["router"]
