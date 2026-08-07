"""The Ollama adapter — same port, same errors, different wire shape.

The interesting divergences from NVIDIA are all here: images ride on the message
rather than in content parts, token counts have different names, a 404 usually
means "nobody pulled the model", and *healthy* has to mean the model is present
rather than merely that a daemon answered.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from app.adapters.document_vlm.base import VLMAdapterConfig
from app.adapters.document_vlm.ollama import OllamaDocumentVLMAdapter, build_ollama_adapter
from app.document_platform.vlm.errors import (
    DocumentVLMBadRequestError,
    DocumentVLMInvalidResponseError,
    DocumentVLMRefusedError,
    DocumentVLMTimeoutError,
    DocumentVLMUnavailableError,
    DocumentVLMUpstreamError,
)

from .conftest import PNG_BYTES, RecordingTransport, invoice_text, ollama_response


def adapter(config, transport: RecordingTransport, sleep=None) -> OllamaDocumentVLMAdapter:
    return OllamaDocumentVLMAdapter(
        config, transport=transport.transport(), **({"sleep": sleep} if sleep else {})
    )


class TestIdentity:
    def test_reports_its_provider_and_model(self, ollama_config) -> None:
        vlm = OllamaDocumentVLMAdapter(ollama_config)
        assert vlm.provider_name() == "ollama"
        assert vlm.model_name() == "qwen2.5vl:7b"


class TestRequestConstruction:
    async def test_posts_to_the_local_chat_endpoint(
        self, ollama_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=ollama_response())]
        await adapter(ollama_config, transport).extract_document(extraction_request)
        assert str(transport.requests[0].url) == "http://localhost:11434/api/chat"

    async def test_sends_no_authorization_header_by_default(
        self, ollama_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=ollama_response())]
        await adapter(ollama_config, transport).extract_document(extraction_request)
        assert "Authorization" not in transport.requests[0].headers

    async def test_authenticates_when_a_proxy_key_is_configured(
        self, transport, extraction_request
    ) -> None:
        """Fronting Ollama with an authenticating proxy is a normal deployment."""
        config = VLMAdapterConfig(
            base_url="http://gateway.internal", model="qwen2.5vl:7b", api_key="proxy-key"
        )
        transport.responses = [httpx.Response(200, json=ollama_response())]
        await adapter(config, transport).extract_document(extraction_request)
        assert transport.requests[0].headers["Authorization"] == "Bearer proxy-key"

    async def test_images_ride_on_the_user_message_as_base64(
        self, ollama_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=ollama_response())]
        await adapter(ollama_config, transport).extract_document(extraction_request)
        user = transport.last_body["messages"][-1]
        assert user["images"] == [base64.b64encode(PNG_BYTES).decode()]
        assert user["content"] == extraction_request.prompt.user

    async def test_requests_json_constrained_decoding(
        self, ollama_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=ollama_response())]
        await adapter(ollama_config, transport).extract_document(extraction_request)
        assert transport.last_body["format"] == "json"
        assert transport.last_body["stream"] is False

    async def test_a_response_schema_constrains_decoding_to_that_schema(
        self, ollama_config, transport, image_payload
    ) -> None:
        from app.document_platform.vlm.ports import VLMExtractionRequest
        from app.document_platform.vlm.prompts import InvoiceExtractionPromptProvider

        prompt = InvoiceExtractionPromptProvider(include_json_schema=True).build(image_payload)
        transport.responses = [httpx.Response(200, json=ollama_response())]
        await adapter(ollama_config, transport).extract_document(
            VLMExtractionRequest(payload=image_payload, prompt=prompt)
        )
        assert isinstance(transport.last_body["format"], dict)

    async def test_generation_options_come_from_the_prompt(
        self, ollama_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=ollama_response())]
        await adapter(ollama_config, transport).extract_document(extraction_request)
        options = transport.last_body["options"]
        assert options["temperature"] == 0.0
        assert options["num_predict"] == extraction_request.prompt.max_output_tokens

    async def test_a_configured_context_window_is_passed_through(
        self, transport, extraction_request
    ) -> None:
        config = VLMAdapterConfig(
            base_url="http://localhost:11434", model="m", extra={"num_ctx": 16384}
        )
        transport.responses = [httpx.Response(200, json=ollama_response())]
        await adapter(config, transport).extract_document(extraction_request)
        assert transport.last_body["options"]["num_ctx"] == 16384


class TestResponseHandling:
    async def test_returns_structured_output(
        self, ollama_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=ollama_response())]
        result = await adapter(ollama_config, transport).extract_document(extraction_request)
        assert result.structured["invoice_number"] == "INV-2026-0042"
        assert result.provider == "ollama"
        assert result.raw_text == invoice_text()

    async def test_maps_ollamas_own_token_counters_onto_the_ports_shape(
        self, ollama_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=ollama_response(counts=(900, 150)))]
        result = await adapter(ollama_config, transport).extract_document(extraction_request)
        assert result.usage.prompt_tokens == 900
        assert result.usage.completion_tokens == 150
        assert result.usage.total_tokens == 1050

    async def test_truncation_is_surfaced(
        self, ollama_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=ollama_response(done_reason="length"))]
        result = await adapter(ollama_config, transport).extract_document(extraction_request)
        assert result.truncated

    async def test_prose_around_the_json_is_recovered_from(
        self, ollama_config, transport, extraction_request
    ) -> None:
        transport.responses = [
            httpx.Response(200, json=ollama_response(f"Sure! {invoice_text()}"))
        ]
        result = await adapter(ollama_config, transport).extract_document(extraction_request)
        assert result.structured["invoice_number"] == "INV-2026-0042"
        assert result.repaired


class TestFailures:
    async def test_a_missing_model_is_named_as_such_with_the_fix(
        self, ollama_config, transport, extraction_request
    ) -> None:
        """The failure operators actually hit. A generic 502 sends them to the
        wrong system entirely."""
        transport.default = httpx.Response(
            404, json={"error": "model 'qwen2.5vl:7b' not found, try pulling it first"}
        )
        with pytest.raises(DocumentVLMUnavailableError) as caught:
            await adapter(ollama_config, transport).extract_document(extraction_request)
        assert "ollama pull qwen2.5vl:7b" in caught.value.message
        assert caught.value.http_status == 503

    async def test_a_missing_model_reported_with_http_200_is_still_caught(
        self, ollama_config, transport, extraction_request
    ) -> None:
        transport.default = httpx.Response(200, json={"error": "model not found"})
        with pytest.raises(DocumentVLMUnavailableError):
            await adapter(ollama_config, transport).extract_document(extraction_request)

    async def test_an_unrelated_404_is_a_bad_request(
        self, ollama_config, transport, extraction_request
    ) -> None:
        transport.default = httpx.Response(404, json={"error": "unknown route"})
        with pytest.raises(DocumentVLMBadRequestError):
            await adapter(ollama_config, transport).extract_document(extraction_request)

    async def test_a_daemon_error_is_upstream_and_retryable(
        self, ollama_config, transport, extraction_request, fake_sleep
    ) -> None:
        transport.default = httpx.Response(500, json={"error": "out of memory"})
        with pytest.raises(DocumentVLMUpstreamError) as caught:
            await adapter(ollama_config, transport, fake_sleep).extract_document(
                extraction_request
            )
        assert caught.value.retryable
        assert "out of memory" in caught.value.message

    async def test_a_timeout_is_typed(
        self, ollama_config, transport, extraction_request, fake_sleep
    ) -> None:
        transport.responses = [httpx.TimeoutException("read timeout")] * 3
        with pytest.raises(DocumentVLMTimeoutError):
            await adapter(ollama_config, transport, fake_sleep).extract_document(
                extraction_request
            )

    async def test_an_empty_message_is_rejected_not_treated_as_an_empty_invoice(
        self, ollama_config, transport, extraction_request
    ) -> None:
        transport.default = httpx.Response(200, json={"message": {"content": ""}})
        with pytest.raises(DocumentVLMInvalidResponseError):
            await adapter(ollama_config, transport).extract_document(extraction_request)

    async def test_a_refusal_is_reported_as_a_refusal(
        self, ollama_config, transport, extraction_request
    ) -> None:
        transport.default = httpx.Response(
            200, json=ollama_response("I'm unable to help with that request.")
        )
        with pytest.raises(DocumentVLMRefusedError):
            await adapter(ollama_config, transport).extract_document(extraction_request)


class TestHealth:
    async def test_healthy_when_the_model_is_pulled(self, ollama_config, transport) -> None:
        transport.default = httpx.Response(
            200, json={"models": [{"name": "qwen2.5vl:7b"}, {"name": "llama3.2:3b"}]}
        )
        health = await adapter(ollama_config, transport).health()
        assert health.healthy
        assert health.detail["model_present"] is True
        assert transport.requests[0].url.path == "/api/tags"

    async def test_unhealthy_when_the_daemon_runs_but_the_model_is_absent(
        self, ollama_config, transport
    ) -> None:
        """A running daemon without the model produces a 404 on the first real
        request, hours after a naive health check said everything was fine."""
        transport.default = httpx.Response(200, json={"models": [{"name": "llama3.2:3b"}]})
        health = await adapter(ollama_config, transport).health()
        assert not health.healthy
        assert "ollama pull qwen2.5vl:7b" in health.detail["reason"]

    async def test_a_bare_model_name_matches_the_latest_tag(self, transport) -> None:
        config = VLMAdapterConfig(base_url="http://localhost:11434", model="qwen2.5vl")
        transport.default = httpx.Response(200, json={"models": [{"name": "qwen2.5vl:latest"}]})
        assert (await adapter(config, transport).health()).healthy

    async def test_unhealthy_when_the_daemon_is_down(self, ollama_config, transport) -> None:
        transport.responses = [httpx.ConnectError("connection refused")]
        health = await adapter(ollama_config, transport).health()
        assert not health.healthy
        assert "connection refused" in health.error or health.error


class TestCost:
    def test_local_inference_is_free_at_the_margin_and_says_why(
        self, ollama_config, extraction_request
    ) -> None:
        estimate = OllamaDocumentVLMAdapter(ollama_config).estimate_cost(extraction_request)
        assert estimate.is_free
        assert estimate.currency == "none"
        assert "local inference" in estimate.basis

    def test_tokens_are_still_estimated_so_budgets_compare(
        self, ollama_config, extraction_request
    ) -> None:
        estimate = OllamaDocumentVLMAdapter(ollama_config).estimate_cost(extraction_request)
        assert estimate.estimated_prompt_tokens > 0


class TestFactory:
    def test_builds_from_settings_alone(self, settings_factory) -> None:
        settings = settings_factory(
            DOCUMENT_VLM_PROVIDER="ollama",
            OLLAMA_BASE_URL="http://gpu-box:11434",
            OLLAMA_MODEL="llama3.2-vision:11b",
        )
        vlm = build_ollama_adapter(settings)
        assert vlm.model_name() == "llama3.2-vision:11b"
        assert vlm.config.base_url == "http://gpu-box:11434"

    def test_a_host_without_a_scheme_is_normalised(self, settings_factory) -> None:
        """Ollama's own service sets OLLAMA_HOST=0.0.0.0:11434, which pydantic
        picks up ahead of .env."""
        settings = settings_factory(
            DOCUMENT_VLM_PROVIDER="ollama", OLLAMA_BASE_URL="0.0.0.0:11434"
        )
        assert build_ollama_adapter(settings).config.base_url == "http://localhost:11434"

    def test_needs_no_api_key(self, settings_factory) -> None:
        settings = settings_factory(DOCUMENT_VLM_PROVIDER="ollama", NVIDIA_API_KEY="")
        assert build_ollama_adapter(settings).config.api_key == ""
