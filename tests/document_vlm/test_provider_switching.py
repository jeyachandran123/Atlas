"""Switching providers: an environment variable, and nothing else.

The claim under test is the expensive one to get wrong. It is checked three
ways:

1. the same configuration object, read twice with a different
   ``DOCUMENT_VLM_PROVIDER``, produces two different adapters;
2. the pipeline produces byte-identical extractions through either of them,
   given equivalent model output;
3. a provider that did not exist when the platform was written can be
   registered and used *without editing a single file under
   ``app/document_platform``*.

Point three is the whole architecture in one test.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest

from app.adapters.document_vlm.nvidia import NvidiaDocumentVLMAdapter
from app.adapters.document_vlm.ollama import OllamaDocumentVLMAdapter
from app.adapters.document_vlm.registry import (
    build_document_vlm,
    describe_document_vlm,
    get_document_vlm,
    register_document_vlm_provider,
    registered_providers,
    reset_document_vlm_cache,
    unregister_document_vlm_provider,
)
from app.document_platform.vlm.errors import (
    DocumentVLMConfigurationError,
    DocumentVLMUnsupportedProviderError,
)
from app.document_platform.vlm.pipeline import DocumentExtractionPipeline
from app.document_platform.vlm.ports import DocumentVLMPort, is_document_vlm

from .conftest import (
    PNG_BYTES,
    RecordingTransport,
    ScriptedDocumentVLM,
    invoice_text,
    nvidia_response,
    ollama_response,
)


@pytest.fixture(autouse=True)
def _clean_registry_cache():
    reset_document_vlm_cache()
    yield
    reset_document_vlm_cache()


class TestSelection:
    def test_both_shipped_providers_are_registered(self) -> None:
        assert {"nvidia", "ollama"} <= set(registered_providers())

    @pytest.mark.parametrize(
        ("provider", "expected"),
        [("nvidia", NvidiaDocumentVLMAdapter), ("ollama", OllamaDocumentVLMAdapter)],
    )
    def test_the_environment_variable_decides(
        self, settings_factory, provider, expected
    ) -> None:
        settings = settings_factory(
            DOCUMENT_VLM_PROVIDER=provider, NVIDIA_API_KEY="nvapi-x"
        )
        assert isinstance(build_document_vlm(settings=settings), expected)

    def test_switching_is_configuration_only(self, settings_factory) -> None:
        """Same call, same code path, different provider — the only difference
        between the two lines is an environment variable."""
        first = build_document_vlm(
            settings=settings_factory(DOCUMENT_VLM_PROVIDER="ollama", NVIDIA_API_KEY="nvapi-x")
        )
        second = build_document_vlm(
            settings=settings_factory(DOCUMENT_VLM_PROVIDER="nvidia", NVIDIA_API_KEY="nvapi-x")
        )
        assert (first.provider_name(), second.provider_name()) == ("ollama", "nvidia")

    def test_the_provider_name_is_case_and_space_insensitive(self, settings_factory) -> None:
        settings = settings_factory(DOCUMENT_VLM_PROVIDER="  NVIDIA  ", NVIDIA_API_KEY="k")
        assert build_document_vlm(settings=settings).provider_name() == "nvidia"

    def test_an_unknown_provider_fails_with_the_list_of_known_ones(
        self, settings_factory
    ) -> None:
        settings = settings_factory(DOCUMENT_VLM_PROVIDER="mistral-vision")
        with pytest.raises(DocumentVLMUnsupportedProviderError) as caught:
            build_document_vlm(settings=settings)
        assert "nvidia" in caught.value.message and "ollama" in caught.value.message

    def test_an_empty_provider_fails_rather_than_defaulting_silently(
        self, settings_factory
    ) -> None:
        settings = settings_factory(DOCUMENT_VLM_PROVIDER="")
        with pytest.raises(DocumentVLMConfigurationError):
            build_document_vlm(settings=settings)

    def test_an_explicit_override_beats_configuration(self, settings_factory) -> None:
        settings = settings_factory(DOCUMENT_VLM_PROVIDER="ollama", NVIDIA_API_KEY="k")
        assert build_document_vlm("nvidia", settings=settings).provider_name() == "nvidia"


class TestCaching:
    def test_the_instance_is_reused_within_one_configuration(self, settings_factory) -> None:
        settings = settings_factory(DOCUMENT_VLM_PROVIDER="ollama")
        assert get_document_vlm(settings=settings) is get_document_vlm(settings=settings)

    def test_a_changed_provider_produces_a_new_instance(self, settings_factory) -> None:
        """A cache that survives a configuration change is a cache that serves
        the old endpoint after a deliberate switch."""
        first = get_document_vlm(settings=settings_factory(DOCUMENT_VLM_PROVIDER="ollama"))
        second = get_document_vlm(
            settings=settings_factory(DOCUMENT_VLM_PROVIDER="nvidia", NVIDIA_API_KEY="k")
        )
        assert first is not second

    def test_a_changed_model_produces_a_new_instance(self, settings_factory) -> None:
        first = get_document_vlm(
            settings=settings_factory(DOCUMENT_VLM_PROVIDER="ollama", OLLAMA_MODEL="a:1")
        )
        second = get_document_vlm(
            settings=settings_factory(DOCUMENT_VLM_PROVIDER="ollama", OLLAMA_MODEL="b:2")
        )
        assert first is not second and second.model_name() == "b:2"


class TestFutureProviders:
    """Adding Claude / Gemini / OpenAI / Qwen Cloud, simulated end to end."""

    def test_a_new_provider_needs_no_platform_change(self, settings_factory) -> None:
        @dataclass
        class ClaudeVisionAdapter(ScriptedDocumentVLM):
            provider: str = "claude"
            model: str = "claude-vision-next"

        try:
            register_document_vlm_provider("claude", lambda settings, **kw: ClaudeVisionAdapter())
            settings = settings_factory(DOCUMENT_VLM_PROVIDER="claude")
            adapter = build_document_vlm(settings=settings)
            assert adapter.provider_name() == "claude"
            assert is_document_vlm(adapter)
        finally:
            unregister_document_vlm_provider("claude")

    async def test_the_pipeline_runs_unchanged_through_a_future_provider(self) -> None:
        """No business logic is touched: the same pipeline, the same schema, the
        same API contract — a provider that did not exist when they were written."""
        pipeline = DocumentExtractionPipeline(
            ScriptedDocumentVLM(provider="gemini", model="gemini-vision-next")
        )
        outcome = await pipeline.extract_invoice(filename="invoice.png", content=PNG_BYTES)
        assert outcome.success
        assert outcome.provider == "gemini"
        assert outcome.data["invoice_number"] == "INV-2026-0042"

    def test_registering_a_name_twice_is_refused(self) -> None:
        """Silent last-import-wins would make which adapter answers a function
        of import order."""
        try:
            register_document_vlm_provider("qwen", lambda settings, **kw: ScriptedDocumentVLM())
            with pytest.raises(DocumentVLMConfigurationError, match="already registered"):
                register_document_vlm_provider("qwen", lambda settings, **kw: ScriptedDocumentVLM())
        finally:
            unregister_document_vlm_provider("qwen")

    def test_a_deliberate_replacement_is_allowed(self) -> None:
        try:
            register_document_vlm_provider("openai", lambda settings, **kw: ScriptedDocumentVLM())
            register_document_vlm_provider(
                "openai",
                lambda settings, **kw: ScriptedDocumentVLM(provider="openai"),
                replace=True,
            )
            assert build_document_vlm("openai", settings=object()).provider_name() == "openai"
        finally:
            unregister_document_vlm_provider("openai")

    def test_a_non_conforming_provider_is_rejected_at_binding_time(
        self, settings_factory
    ) -> None:
        """Not at first use, in the middle of a customer's upload."""

        class NotAnAdapter:
            def provider_name(self) -> str:
                return "broken"

        try:
            register_document_vlm_provider("broken", lambda settings, **kw: NotAnAdapter())
            with pytest.raises(DocumentVLMConfigurationError, match="does not implement"):
                build_document_vlm("broken", settings=settings_factory())
        finally:
            unregister_document_vlm_provider("broken")


class TestEquivalence:
    """Given equivalent model output, the two providers are indistinguishable."""

    async def _extract(self, adapter, payload_bytes: bytes) -> dict:
        pipeline = DocumentExtractionPipeline(adapter)
        outcome = await pipeline.extract_invoice(
            filename="invoice.png", content=payload_bytes, request_id="fixed-id"
        )
        return outcome.data

    async def test_nvidia_and_ollama_produce_identical_extractions(
        self, nvidia_config, ollama_config
    ) -> None:
        nvidia_transport = RecordingTransport(
            default=httpx.Response(200, json=nvidia_response(invoice_text()))
        )
        ollama_transport = RecordingTransport(
            default=httpx.Response(200, json=ollama_response(invoice_text()))
        )
        nvidia = NvidiaDocumentVLMAdapter(
            nvidia_config, transport=nvidia_transport.transport()
        )
        ollama = OllamaDocumentVLMAdapter(
            ollama_config, transport=ollama_transport.transport()
        )

        from_nvidia = await self._extract(nvidia, PNG_BYTES)
        from_ollama = await self._extract(ollama, PNG_BYTES)
        assert from_nvidia == from_ollama

    async def test_both_providers_raise_the_same_error_type_for_the_same_failure(
        self, nvidia_config, ollama_config
    ) -> None:
        from app.document_platform.vlm.errors import DocumentVLMUpstreamError

        for config, cls, transport in (
            (nvidia_config, NvidiaDocumentVLMAdapter, RecordingTransport(
                default=httpx.Response(500, json={"error": "boom"}))),
            (ollama_config, OllamaDocumentVLMAdapter, RecordingTransport(
                default=httpx.Response(500, json={"error": "boom"}))),
        ):
            async def _sleep(_):
                return None

            adapter = cls(config, transport=transport.transport(), sleep=_sleep)
            with pytest.raises(DocumentVLMUpstreamError):
                await DocumentExtractionPipeline(adapter).extract_invoice(
                    filename="invoice.png", content=PNG_BYTES
                )


class TestDescription:
    def test_describes_the_bound_provider_without_credentials(
        self, settings_factory
    ) -> None:
        described = describe_document_vlm(
            settings_factory(
                DOCUMENT_VLM_PROVIDER="nvidia",
                NVIDIA_API_KEY="nvapi-super-secret",
                NVIDIA_BASE_URL="https://integrate.api.nvidia.com/v1",
            )
        )
        assert described["provider"] == "nvidia"
        assert described["api_key_configured"] is True
        assert "nvapi-super-secret" not in str(described)

    def test_reports_an_absent_key_as_absent(self, settings_factory) -> None:
        described = describe_document_vlm(
            settings_factory(DOCUMENT_VLM_PROVIDER="nvidia", NVIDIA_API_KEY="")
        )
        assert described["api_key_configured"] is False

    def test_lists_every_registered_provider_for_the_operator(
        self, settings_factory
    ) -> None:
        described = describe_document_vlm(settings_factory(DOCUMENT_VLM_PROVIDER="ollama"))
        assert {"nvidia", "ollama"} <= set(described["available_providers"])


class TestTyping:
    def test_the_registry_returns_the_port_type(self, settings_factory) -> None:
        adapter: DocumentVLMPort = build_document_vlm(
            settings=settings_factory(DOCUMENT_VLM_PROVIDER="ollama")
        )
        assert isinstance(adapter, DocumentVLMPort)
