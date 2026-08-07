"""Prompt management: versioned, immutable, and outside the adapters.

The property under test throughout is *attribution*. Every extraction records
which wording produced it, and a wording that can change under a fixed version
number makes that record worthless.
"""

from __future__ import annotations

import pytest

from app.document_platform.vlm.errors import DocumentVLMConfigurationError
from app.document_platform.vlm.ports import DocumentImage, DocumentPayload
from app.document_platform.vlm.prompts import (
    INVOICE_EXTRACTION_PROMPT_ID,
    InvoiceExtractionPromptProvider,
    PromptProvider,
    PromptTemplate,
)


class TestRendering:
    def test_the_prompt_is_pinned_to_a_version(self, prompts, image_payload) -> None:
        prompt = prompts.build(image_payload)
        assert prompt.prompt_id == INVOICE_EXTRACTION_PROMPT_ID
        assert prompt.version == "1.0.0"
        assert prompt.pinned == "invoice.extract@1.0.0"

    def test_the_system_prompt_forbids_invention(self, prompts, image_payload) -> None:
        """The rule that matters most: a plausible guess is not an answer."""
        system = prompts.build(image_payload).system.lower()
        assert "never infer" in system
        assert "null" in system

    def test_the_document_text_reaches_the_model(self, prompts, image_payload) -> None:
        prompt = prompts.build(image_payload)
        assert "INV-2026-0042" in prompt.user

    def test_the_model_is_told_the_text_came_from_ocr(self, prompts, image_payload) -> None:
        """A model shown OCR without being told treats garbled characters as
        the document's own wording."""
        assert "OCR" in prompts.build(image_payload).user

    def test_the_model_is_told_pixels_are_authoritative_when_both_exist(
        self, prompts, image_payload
    ) -> None:
        assert "trust the images" in prompts.build(image_payload).user

    def test_a_text_only_payload_says_so(self, prompts, text_only_payload) -> None:
        user = prompts.build(text_only_payload).user
        assert "page image" not in user
        assert "embedded text layer" in user

    def test_long_text_is_truncated_and_the_model_is_told(self) -> None:
        provider = InvoiceExtractionPromptProvider(max_text_chars=100)
        payload = DocumentPayload(ocr_text="X" * 5000, text_source="ocr")
        user = provider.build(payload).user
        assert "truncated" in user, "silent truncation reads as a short document"
        body = user.split("--- BEGIN DOCUMENT TEXT ---")[1].split("--- END DOCUMENT")[0]
        assert body.strip() == "X" * 100

    def test_rendering_is_deterministic(self, prompts, image_payload) -> None:
        first = prompts.build(image_payload)
        second = prompts.build(image_payload)
        assert first.system == second.system and first.user == second.user


class TestVersioning:
    def test_an_unregistered_configured_version_fails_at_construction(self) -> None:
        """Loudly, at startup — not silently, at the first upload."""
        with pytest.raises(DocumentVLMConfigurationError, match="not registered"):
            InvoiceExtractionPromptProvider(version="9.9.9")

    def test_an_unregistered_requested_version_fails_at_build(
        self, prompts, image_payload
    ) -> None:
        with pytest.raises(DocumentVLMConfigurationError, match="9.9.9"):
            prompts.build(image_payload, version="9.9.9")

    def test_a_new_version_can_be_registered_and_selected(self, image_payload) -> None:
        provider = InvoiceExtractionPromptProvider()
        provider.register(
            PromptTemplate(
                prompt_id=INVOICE_EXTRACTION_PROMPT_ID,
                version="1.1.0",
                system="terse system",
                user_template="terse: {schema}{sources}",
            )
        )
        assert provider.versions() == ("1.0.0", "1.1.0")
        assert provider.build(image_payload, version="1.1.0").system == "terse system"
        assert provider.build(image_payload).version == "1.0.0", "default is unchanged"

    def test_an_existing_version_cannot_be_edited(self) -> None:
        """Two records pinned to 1.0.0 must have been produced by the same
        words, or provenance is decoration."""
        provider = InvoiceExtractionPromptProvider()
        with pytest.raises(DocumentVLMConfigurationError, match="already registered"):
            provider.register(
                PromptTemplate(
                    prompt_id=INVOICE_EXTRACTION_PROMPT_ID,
                    version="1.0.0",
                    system="different",
                    user_template="different {schema}{sources}",
                )
            )

    def test_both_versions_coexist_so_they_can_be_compared(self, image_payload) -> None:
        provider = InvoiceExtractionPromptProvider()
        provider.register(
            PromptTemplate(
                prompt_id=INVOICE_EXTRACTION_PROMPT_ID,
                version="2.0.0",
                system="v2",
                user_template="v2 {schema}{sources}",
            )
        )
        old = provider.build(image_payload, version="1.0.0")
        new = provider.build(image_payload, version="2.0.0")
        assert old.system != new.system
        assert (old.version, new.version) == ("1.0.0", "2.0.0")


class TestConfiguration:
    def test_output_limits_come_from_configuration(self, image_payload) -> None:
        provider = InvoiceExtractionPromptProvider(max_output_tokens=777, temperature=0.25)
        prompt = provider.build(image_payload)
        assert prompt.max_output_tokens == 777
        assert prompt.temperature == 0.25

    def test_per_call_overrides_win(self, prompts, image_payload) -> None:
        prompt = prompts.build(image_payload, max_output_tokens=64, temperature=0.9)
        assert (prompt.max_output_tokens, prompt.temperature) == (64, 0.9)

    def test_a_json_schema_is_attached_only_when_asked_for(self, image_payload) -> None:
        assert InvoiceExtractionPromptProvider().build(image_payload).response_schema is None
        constrained = InvoiceExtractionPromptProvider(include_json_schema=True)
        assert constrained.build(image_payload).response_schema is not None

    def test_the_provider_describes_itself_for_the_api(self, prompts) -> None:
        described = prompts.describe()
        assert described["prompt_id"] == INVOICE_EXTRACTION_PROMPT_ID
        assert described["available_versions"] == ["1.0.0"]


class TestSeam:
    def test_the_concrete_provider_satisfies_the_seam(self, prompts) -> None:
        assert isinstance(prompts, PromptProvider)

    def test_any_object_with_the_two_methods_is_substitutable(self, image_payload) -> None:
        class DatabaseBackedPrompts:
            def build(self, payload, **options):  # noqa: ANN001, ANN003
                from app.document_platform.vlm.ports import ExtractionPrompt

                return ExtractionPrompt(
                    system="s", user="u", prompt_id="db.invoice", version="7"
                )

            def versions(self):
                return ("7",)

        assert isinstance(DatabaseBackedPrompts(), PromptProvider)

    def test_no_adapter_composes_a_prompt(self) -> None:
        """Port obligation V5, checked in source: an adapter that builds its own
        instructions has silently taken ownership of extraction quality."""
        from pathlib import Path

        adapters = Path("app/adapters/document_vlm")
        for module in adapters.glob("*.py"):
            source = module.read_text(encoding="utf-8")
            assert "InvoiceExtractionPromptProvider" not in source, module.name
            assert "You are a" not in source, f"{module.name} contains prompt wording"


class TestPayloadDescription:
    def test_page_count_is_reported_to_the_model(self) -> None:
        payload = DocumentPayload(
            images=tuple(
                DocumentImage(data=b"x", media_type="image/png", page=i) for i in (1, 2, 3)
            )
        )
        assert "3 page images" in InvoiceExtractionPromptProvider().build(payload).user

    def test_a_single_page_is_described_in_the_singular(self, image_payload) -> None:
        assert "1 page image " in InvoiceExtractionPromptProvider().build(image_payload).user
