"""The extraction pipeline, end to end, against a scripted provider.

Every test here runs the *real* pipeline — real payload builder, real prompt
provider, real JSON recovery, real schema validation — with only the model
replaced. That is the arrangement that tests the platform rather than the
model: the stages that decide whether an invoice is correct are all exercised,
and none of them can pass by accident because a 7-billion-parameter model
happened to be having a good day.
"""

from __future__ import annotations

import pytest

from app.document_platform.processing.ocr import AbstractOcrProvider, OcrResult, OcrService
from app.document_platform.vlm.errors import (
    DocumentTooLargeError,
    DocumentVLMTimeoutError,
    EmptyDocumentError,
    InvoiceSchemaError,
    UnsupportedDocumentError,
)
from app.document_platform.vlm.payload import DocumentPayloadBuilder
from app.document_platform.vlm.pipeline import DocumentExtractionPipeline
from app.document_platform.vlm.prompts import InvoiceExtractionPromptProvider

from .conftest import PNG_BYTES, VALID_INVOICE_JSON, ScriptedDocumentVLM


@pytest.fixture
def pipeline(scripted_vlm: ScriptedDocumentVLM) -> DocumentExtractionPipeline:
    return DocumentExtractionPipeline(scripted_vlm)


class TestHappyPath:
    async def test_it_extracts_an_invoice_from_an_image(self, pipeline) -> None:
        outcome = await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert outcome.success
        assert outcome.data["invoice_number"] == "INV-2026-0042"
        assert outcome.data["totals"]["grand_total"] == 305.2

    async def test_it_reports_the_provider_and_model_that_answered(
        self, pipeline, scripted_vlm
    ) -> None:
        outcome = await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert (outcome.provider, outcome.model) == (
            scripted_vlm.provider,
            scripted_vlm.model,
        )

    async def test_it_records_the_prompt_and_schema_versions(self, pipeline) -> None:
        """An extraction without the record of what produced it cannot be
        re-examined when a number turns out to be wrong — and one always does."""
        outcome = await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert outcome.prompt_id == "invoice.extract"
        assert outcome.prompt_version == "1.0.0"
        assert outcome.schema_version == "1.0.0"

    async def test_it_times_every_stage(self, pipeline) -> None:
        outcome = await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert set(outcome.stages) == {"payload", "prompt", "vlm", "validation"}
        assert outcome.processing_time_ms >= 0

    async def test_it_reports_what_actually_reached_the_model(self, pipeline) -> None:
        """The difference between "the model missed it" and "the page was never
        sent" — invisible without this."""
        outcome = await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert outcome.document["images_sent"] == 1
        assert outcome.document["media_type"] == "image/png"
        assert outcome.document["ocr_provider"] == "null"

    async def test_the_correlation_id_is_carried_into_the_provider_call(
        self, pipeline, scripted_vlm
    ) -> None:
        await pipeline.extract_invoice(
            filename="invoice.png", content=PNG_BYTES, request_id="corr-99"
        )
        assert scripted_vlm.calls[0].request_id == "corr-99"

    async def test_a_correlation_id_is_minted_when_the_caller_omits_one(
        self, pipeline
    ) -> None:
        outcome = await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert len(outcome.request_id) == 36


class TestOcrStage:
    async def test_it_uses_the_platforms_existing_ocr_implementation(self) -> None:
        """Reuse, not a second OCR path: one platform, one answer to "what did
        we read off this page"."""

        class SpyOcr(AbstractOcrProvider):
            name = "spy"

            def __init__(self) -> None:
                self.calls = 0

            async def extract_text(self, image_bytes: bytes, image_format: str) -> OcrResult:
                self.calls += 1
                return OcrResult(text="INVOICE INV-2026-0042", performed=True, provider=self.name)

        spy = SpyOcr()
        vlm = ScriptedDocumentVLM()
        pipeline = DocumentExtractionPipeline(
            vlm, payload_builder=DocumentPayloadBuilder(ocr=OcrService(spy))
        )
        outcome = await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert spy.calls == 1
        assert outcome.document["ocr_provider"] == "spy"
        assert outcome.document["text_source"] == "ocr"

    async def test_ocr_text_reaches_the_prompt(self) -> None:
        class TextOcr(AbstractOcrProvider):
            name = "text"

            async def extract_text(self, image_bytes: bytes, image_format: str) -> OcrResult:
                return OcrResult(text="TOTAL DUE 305.20", performed=True, provider=self.name)

        vlm = ScriptedDocumentVLM()
        pipeline = DocumentExtractionPipeline(
            vlm, payload_builder=DocumentPayloadBuilder(ocr=OcrService(TextOcr()))
        )
        await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert "TOTAL DUE 305.20" in vlm.calls[0].prompt.user

    async def test_a_broken_ocr_provider_degrades_instead_of_failing(self) -> None:
        """With pixels in the payload the model still has the document."""

        class BrokenOcr(AbstractOcrProvider):
            name = "broken"

            async def extract_text(self, image_bytes: bytes, image_format: str) -> OcrResult:
                raise RuntimeError("tesseract binary missing")

        pipeline = DocumentExtractionPipeline(
            ScriptedDocumentVLM(),
            payload_builder=DocumentPayloadBuilder(ocr=OcrService(BrokenOcr())),
        )
        outcome = await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert outcome.success


class TestInputRejection:
    async def test_an_unsupported_type_is_refused_before_any_model_is_called(
        self, pipeline, scripted_vlm
    ) -> None:
        with pytest.raises(UnsupportedDocumentError):
            await pipeline.extract_invoice(filename="notes.docx", content=b"PK\x03\x04junk")
        assert scripted_vlm.calls == [], "no provider spend on a document we cannot read"

    async def test_an_empty_upload_is_refused(self, pipeline) -> None:
        with pytest.raises(EmptyDocumentError):
            await pipeline.extract_invoice(filename="invoice.pdf", content=b"")

    async def test_an_oversized_upload_is_refused(self, scripted_vlm) -> None:
        pipeline = DocumentExtractionPipeline(
            scripted_vlm, payload_builder=DocumentPayloadBuilder(max_bytes=1024)
        )
        with pytest.raises(DocumentTooLargeError, match="MB limit"):
            await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES * 1000)


class TestProviderFailures:
    async def test_a_provider_error_propagates_untranslated(self, scripted_vlm) -> None:
        """The API layer maps errors to status codes; the pipeline must not
        flatten a timeout into a generic failure on the way there."""
        scripted_vlm.error = DocumentVLMTimeoutError(
            "provider timed out", provider="scripted", model="scripted-vlm-1"
        )
        pipeline = DocumentExtractionPipeline(scripted_vlm)
        with pytest.raises(DocumentVLMTimeoutError) as caught:
            await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert caught.value.retryable is True

    async def test_an_empty_model_answer_becomes_a_schema_error_not_an_empty_invoice(
        self, scripted_vlm
    ) -> None:
        scripted_vlm.structured = {}
        pipeline = DocumentExtractionPipeline(scripted_vlm)
        with pytest.raises(InvoiceSchemaError) as caught:
            await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert any("no invoice fields" in v for v in caught.value.violations)

    async def test_a_non_invoice_answer_is_rejected_with_its_violations(
        self, scripted_vlm
    ) -> None:
        scripted_vlm.structured = {"greeting": "hello"}
        pipeline = DocumentExtractionPipeline(scripted_vlm)
        with pytest.raises(InvoiceSchemaError) as caught:
            await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert caught.value.violations


class TestWarnings:
    async def test_schema_warnings_are_surfaced_not_swallowed(self, scripted_vlm) -> None:
        scripted_vlm.structured = {"invoice_number": "INV-1"}
        pipeline = DocumentExtractionPipeline(scripted_vlm)
        outcome = await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert outcome.success
        assert any("missing expected field" in w for w in outcome.warnings)

    async def test_a_truncated_answer_warns_first(self, scripted_vlm) -> None:
        """An invoice with three line items that should have had seven is the
        worst kind of wrong: it looks complete."""
        scripted_vlm.finish_reason = "length"
        pipeline = DocumentExtractionPipeline(scripted_vlm)
        outcome = await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert "output-token limit" in outcome.warnings[0]

    async def test_json_repair_is_reported_to_the_caller(self, scripted_vlm) -> None:
        scripted_vlm.repaired = True
        pipeline = DocumentExtractionPipeline(scripted_vlm)
        outcome = await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert outcome.json_repaired is True


class TestSubstitutability:
    async def test_two_providers_produce_identical_data_from_identical_output(self) -> None:
        """The substitution claim, stated as an equality: same model output in,
        byte-identical extraction out, whichever provider carried it."""
        a = DocumentExtractionPipeline(ScriptedDocumentVLM(provider="nvidia-like"))
        b = DocumentExtractionPipeline(ScriptedDocumentVLM(provider="ollama-like"))
        first = await a.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        second = await b.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert first.data == second.data
        assert first.warnings == second.warnings
        assert first.provider != second.provider, "only the label differs"

    async def test_the_pipeline_reports_health_through_the_port(self, pipeline) -> None:
        health = await pipeline.health()
        assert health.healthy and health.provider == "scripted"

    def test_cost_is_estimable_through_the_pipeline(self, pipeline) -> None:
        from app.document_platform.vlm.payload import PayloadBuildReport
        from app.document_platform.vlm.ports import DocumentPayload

        report = PayloadBuildReport(
            payload=DocumentPayload(ocr_text="INVOICE"),
            extension=".pdf",
            ocr_performed=False,
            ocr_provider="null",
        )
        estimate = pipeline.estimate_cost(report)
        assert estimate["provider"] == "scripted"
        assert estimate["estimated_completion_tokens"] > 0


class TestPromptVersionPinning:
    async def test_a_caller_can_pin_a_prompt_version(self, scripted_vlm) -> None:
        from app.document_platform.vlm.prompts import PromptTemplate

        prompts = InvoiceExtractionPromptProvider()
        prompts.register(
            PromptTemplate(
                prompt_id="invoice.extract",
                version="1.1.0",
                system="v1.1 system",
                user_template="v1.1 {schema}{sources}",
            )
        )
        pipeline = DocumentExtractionPipeline(scripted_vlm, prompts=prompts)
        outcome = await pipeline.extract_invoice(
            filename="invoice.png", content=PNG_BYTES, prompt_version="1.1.0"
        )
        assert outcome.prompt_version == "1.1.0"
        assert scripted_vlm.calls[0].prompt.system == "v1.1 system"

    async def test_the_default_version_is_used_when_none_is_pinned(
        self, pipeline
    ) -> None:
        outcome = await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert outcome.prompt_version == "1.0.0"


class TestNoBusinessLogicLeaksIntoTheAdapter:
    async def test_the_adapter_receives_a_prompt_it_did_not_compose(
        self, pipeline, scripted_vlm
    ) -> None:
        await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        prompt = scripted_vlm.calls[0].prompt
        assert prompt.prompt_id and prompt.version
        assert "invoice" in prompt.user.lower()

    async def test_the_adapter_is_never_asked_to_validate(self, scripted_vlm) -> None:
        """Validation happens after the port returns: the adapter's structured
        output goes in unmodified, and the platform decides what it means."""
        scripted_vlm.structured = {**VALID_INVOICE_JSON, "invoiceNumber": "ALIAS"}
        pipeline = DocumentExtractionPipeline(scripted_vlm)
        outcome = await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert outcome.data["invoice_number"] == "INV-2026-0042"
