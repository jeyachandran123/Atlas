"""The invoice extraction pipeline.

    upload → payload (OCR) → prompt → DocumentVLMPort → JSON → invoice schema → result

Every stage above is the platform's. The only thing this file knows about the
model is that something implementing ``DocumentVLMPort`` was handed to its
constructor — it cannot tell whether that something crosses the internet or
talks to a GPU under the desk, and nothing here would change if the answer
changed tomorrow. This module names no provider, and a test reads it to be
sure.

That is the whole point of the exercise: the sequence of decisions that turns a
scanned page into a posted invoice is expensive to get right and must not be
re-derived per provider.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.document_platform.vlm.errors import (
    DocumentExtractionError,
    DocumentVLMError,
    InvoiceSchemaError,
)
from app.document_platform.vlm.invoice_schema import (
    INVOICE_SCHEMA_VERSION,
    InvoiceSchemaValidator,
)
from app.document_platform.vlm.observability import (
    record_extraction,
    record_stage,
)
from app.document_platform.vlm.payload import DocumentPayloadBuilder, PayloadBuildReport
from app.document_platform.vlm.ports import (
    DocumentVLMPort,
    ProviderHealth,
    TokenUsage,
    VLMExtractionRequest,
)
from app.document_platform.vlm.prompts import InvoiceExtractionPromptProvider, PromptProvider


@dataclass(frozen=True, slots=True)
class ExtractionOutcome:
    """One completed extraction, with everything needed to explain it.

    Carries provenance (provider, model, prompt version, schema version) beside
    the data, because an extracted invoice without the record of what produced
    it cannot be re-examined when a number turns out to be wrong — and one
    always does.
    """

    success: bool
    provider: str
    model: str
    processing_time_ms: float
    data: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    request_id: str = ""
    prompt_id: str = ""
    prompt_version: str = ""
    schema_version: str = INVOICE_SCHEMA_VERSION
    usage: TokenUsage = TokenUsage()
    retry_count: int = 0
    json_repaired: bool = False
    stages: Mapping[str, float] = field(default_factory=dict)
    document: Mapping[str, Any] = field(default_factory=dict)
    """Provenance of the *input*: page count, text source, OCR provider — the
    difference between "the model missed it" and "the page never reached it"."""


class DocumentExtractionPipeline:
    """Runs the extraction. Provider-agnostic by construction.

    Collaborators are injected and each has a default, so a caller that wants
    the standard behaviour writes ``DocumentExtractionPipeline(vlm)`` and a test
    that wants to isolate one stage replaces exactly that stage.
    """

    def __init__(
        self,
        vlm: DocumentVLMPort,
        *,
        payload_builder: DocumentPayloadBuilder | None = None,
        prompts: PromptProvider | None = None,
        validator: InvoiceSchemaValidator | None = None,
    ) -> None:
        self._vlm = vlm
        self._payloads = payload_builder or DocumentPayloadBuilder()
        self._prompts = prompts or InvoiceExtractionPromptProvider()
        self._validator = validator or InvoiceSchemaValidator()

    # ── introspection ────────────────────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return self._vlm.provider_name()

    @property
    def model_name(self) -> str:
        return self._vlm.model_name()

    @property
    def prompts(self) -> PromptProvider:
        """The bound prompt provider — so the API can report which wording and
        which version produced an extraction without reaching into internals."""
        return self._prompts

    async def health(self) -> ProviderHealth:
        """Whether the bound provider can serve a request. Never raises."""
        return await self._vlm.health()

    # ── the pipeline ─────────────────────────────────────────────────────────

    async def extract_invoice(
        self,
        *,
        filename: str,
        content: bytes,
        declared_mime: str | None = None,
        request_id: str | None = None,
        prompt_version: str | None = None,
    ) -> ExtractionOutcome:
        """Extract one invoice, or raise a typed error explaining why not.

        Raises ``UnsupportedDocumentError``, ``DocumentTooLargeError`` or
        ``EmptyDocumentError`` when the input is the problem, a
        ``DocumentVLMError`` when the provider is, and ``InvoiceSchemaError``
        when the model answered with something that is not an invoice. It never
        returns a successful outcome carrying invented data — an extraction that
        did not happen must be visibly absent, not quietly empty.
        """
        correlation_id = request_id or str(uuid.uuid4())
        provider = self._vlm.provider_name()
        started = time.perf_counter()
        stages: dict[str, float] = {}

        try:
            # 1 — payload: decode, OCR, page selection.
            with _stage("payload", provider, stages):
                report: PayloadBuildReport = await self._payloads.build(
                    filename=filename, content=content, declared_mime=declared_mime
                )

            # 2 — prompt: versioned, built outside the adapter.
            with _stage("prompt", provider, stages):
                prompt = self._prompts.build(report.payload, version=prompt_version)
        except DocumentExtractionError:
            record_extraction("invoice", provider, "input_rejected")
            raise

        # 3 — the model. The only line in this file that touches a provider,
        #     and it does so through the port.
        request = VLMExtractionRequest(
            payload=report.payload,
            prompt=prompt,
            request_id=correlation_id,
            metadata={
                "filename": filename,
                "text_source": report.payload.text_source,
                "page_count": report.payload.page_count,
            },
        )
        try:
            with _stage("vlm", provider, stages):
                result = await self._vlm.extract_document(request)
        except DocumentVLMError as exc:
            record_extraction("invoice", provider, "provider_error")
            raise exc

        # 4 — validation against the platform's schema.
        with _stage("validation", provider, stages):
            validation = self._validator.validate(result.structured)

        if not validation.valid:
            record_extraction("invoice", provider, "schema_error")
            raise InvoiceSchemaError(
                "the model's response did not validate against the invoice schema: "
                + "; ".join(validation.errors),
                violations=validation.errors,
                provider=provider,
                model=result.model,
                request_id=correlation_id,
                raw_excerpt=result.raw_text[:1000],
            )

        warnings = list(validation.warnings)
        if result.truncated:
            # A truncated answer is a *fragment* presented as a whole. Saying so
            # is the difference between an invoice with three line items and an
            # invoice that had seven.
            warnings.insert(
                0,
                "the model stopped at its output-token limit; the extraction may "
                "be incomplete",
            )
        if report.notes:
            warnings.extend(report.notes)

        record_extraction("invoice", provider, "success")
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        return ExtractionOutcome(
            success=True,
            provider=result.provider,
            model=result.model,
            processing_time_ms=round(elapsed_ms, 2),
            data=validation.data,
            warnings=tuple(warnings),
            request_id=correlation_id,
            prompt_id=prompt.prompt_id,
            prompt_version=prompt.version,
            schema_version=validation.schema_version,
            usage=result.usage,
            retry_count=result.retry_count,
            json_repaired=result.repaired,
            stages=dict(stages),
            document={
                "filename": filename,
                "media_type": report.payload.media_type,
                "page_count": report.payload.page_count,
                "images_sent": len(report.payload.images),
                "text_source": report.payload.text_source,
                "text_chars": len(report.payload.ocr_text),
                "ocr_provider": report.ocr_provider,
                "ocr_performed": report.ocr_performed,
            },
        )

    def estimate_cost(self, payload_report: PayloadBuildReport) -> dict[str, Any]:
        """What extracting this document would cost, before it is spent.

        Exposed on the pipeline rather than only on the port so a caller can ask
        without having to know how a request is assembled.
        """
        prompt = self._prompts.build(payload_report.payload)
        estimate = self._vlm.estimate_cost(
            VLMExtractionRequest(payload=payload_report.payload, prompt=prompt)
        )
        return {
            "provider": self._vlm.provider_name(),
            "model": self._vlm.model_name(),
            "amount": estimate.amount,
            "currency": estimate.currency,
            "estimated_prompt_tokens": estimate.estimated_prompt_tokens,
            "estimated_completion_tokens": estimate.estimated_completion_tokens,
            "basis": estimate.basis,
        }


class _stage:
    """Time one stage, record it, and let the exception through untouched.

    A context manager rather than a decorator because the stages are inline
    steps of one method, and reading the pipeline top to bottom is worth more
    than saving four lines.
    """

    __slots__ = ("_into", "_name", "_provider", "_started")

    def __init__(self, name: str, provider: str, into: dict[str, float]) -> None:
        self._name = name
        self._provider = provider
        self._into = into

    def __enter__(self) -> _stage:
        self._started = time.perf_counter()
        return self

    def __exit__(self, *_: object) -> bool:
        elapsed = time.perf_counter() - self._started
        self._into[self._name] = round(elapsed * 1000.0, 2)
        record_stage(self._name, self._provider, elapsed)
        return False


__all__ = [
    "DocumentExtractionPipeline",
    "ExtractionOutcome",
]
