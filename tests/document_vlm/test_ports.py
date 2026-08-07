"""The port itself: conformance, and the invariants its DTOs refuse to break.

These are the tests that keep substitution real. If ``ScriptedDocumentVLM`` —
a dataclass with five methods and no inheritance — satisfies the same protocol
as an adapter that speaks HTTP to NVIDIA, then the platform genuinely cannot
tell them apart, which is the entire claim.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from app.adapters.document_vlm.base import VLMAdapterConfig
from app.adapters.document_vlm.nvidia import NvidiaDocumentVLMAdapter
from app.adapters.document_vlm.ollama import OllamaDocumentVLMAdapter
from app.document_platform.vlm.ports import (
    DOCUMENT_VLM_PORT_VERSION,
    CostEstimate,
    DocumentImage,
    DocumentPayload,
    DocumentVLMPort,
    ExtractionPrompt,
    ProviderHealth,
    TokenUsage,
    VLMExtractionResult,
    is_document_vlm,
)

from .conftest import ScriptedDocumentVLM


class TestConformance:
    def test_port_is_versioned(self) -> None:
        assert DOCUMENT_VLM_PORT_VERSION == "1.0.0"

    @pytest.mark.parametrize(
        "adapter",
        [
            NvidiaDocumentVLMAdapter(
                VLMAdapterConfig(base_url="https://x.test/v1", model="m", api_key="k")
            ),
            OllamaDocumentVLMAdapter(
                VLMAdapterConfig(base_url="http://localhost:11434", model="m")
            ),
            ScriptedDocumentVLM(),
        ],
        ids=["nvidia", "ollama", "scripted"],
    )
    def test_every_implementation_satisfies_the_port(self, adapter: object) -> None:
        assert is_document_vlm(adapter)
        assert isinstance(adapter, DocumentVLMPort)

    def test_the_two_shipped_adapters_expose_identical_surfaces(self) -> None:
        """Not "both have the methods" — the *same* methods, so business logic
        written against one runs unchanged against the other."""
        required = {
            "provider_name",
            "model_name",
            "extract_document",
            "health",
            "estimate_cost",
        }
        for adapter in (NvidiaDocumentVLMAdapter, OllamaDocumentVLMAdapter):
            assert required <= set(dir(adapter))

    def test_a_partial_implementation_is_rejected(self) -> None:
        class MissingCostEstimate:
            def provider_name(self) -> str:
                return "half"

            def model_name(self) -> str:
                return "half"

            async def extract_document(self, request):  # noqa: ANN001
                ...

            async def health(self):
                ...

        assert not is_document_vlm(MissingCostEstimate())


class TestDocumentImage:
    def test_rejects_empty_pixels(self) -> None:
        with pytest.raises(ValueError, match="no bytes"):
            DocumentImage(data=b"", media_type="image/png")

    def test_rejects_a_non_image_media_type(self) -> None:
        with pytest.raises(ValueError, match="image/"):
            DocumentImage(data=b"x", media_type="application/pdf")

    def test_is_immutable(self) -> None:
        """Pixels handed to a provider must be the pixels the pipeline read."""
        image = DocumentImage(data=b"x", media_type="image/png")
        with pytest.raises(FrozenInstanceError):
            image.data = b"y"  # type: ignore[misc]


class TestDocumentPayload:
    def test_refuses_a_payload_with_neither_pixels_nor_text(self) -> None:
        """The failure this prevents is a model inventing an invoice from
        nothing, which no downstream validation can detect."""
        with pytest.raises(ValueError, match="pixels, text, or both"):
            DocumentPayload()

    def test_text_alone_is_a_valid_payload(self) -> None:
        payload = DocumentPayload(ocr_text="INVOICE 1")
        assert payload.has_text and not payload.has_images

    def test_images_alone_are_a_valid_payload(self) -> None:
        payload = DocumentPayload(
            images=(DocumentImage(data=b"x", media_type="image/png"),)
        )
        assert payload.has_images and not payload.has_text

    def test_reports_total_image_bytes(self) -> None:
        payload = DocumentPayload(
            images=(
                DocumentImage(data=b"1234", media_type="image/png"),
                DocumentImage(data=b"12", media_type="image/jpeg"),
            )
        )
        assert payload.total_image_bytes == 6


class TestExtractionPrompt:
    def test_requires_instructions(self) -> None:
        with pytest.raises(ValueError, match="empty instructions"):
            ExtractionPrompt(system="s", user="   ", prompt_id="p", version="1")

    def test_requires_identity(self) -> None:
        with pytest.raises(ValueError, match="id and version"):
            ExtractionPrompt(system="s", user="u", prompt_id="", version="")

    def test_pins_id_and_version(self) -> None:
        prompt = ExtractionPrompt(system="s", user="u", prompt_id="invoice", version="2.1.0")
        assert prompt.pinned == "invoice@2.1.0"


class TestResultDtos:
    def test_unreported_usage_is_absent_not_zero(self) -> None:
        """A zero that means "not reported" is a lie that reaches a cost
        dashboard as a fact."""
        assert TokenUsage().reported is False
        assert TokenUsage(prompt_tokens=0).reported is True

    def test_truncation_is_visible_on_the_result(self) -> None:
        result = VLMExtractionResult(
            structured={},
            raw_text="",
            provider="p",
            model="m",
            latency_ms=1.0,
            finish_reason="length",
        )
        assert result.truncated

    def test_a_free_provider_says_so_without_pretending_to_be_priced(self) -> None:
        assert CostEstimate().is_free

    def test_health_serialises_without_secrets(self) -> None:
        health = ProviderHealth(
            healthy=True, provider="p", model="m", detail={"endpoint": "http://x"}
        )
        assert health.as_dict()["detail"] == {"endpoint": "http://x"}
