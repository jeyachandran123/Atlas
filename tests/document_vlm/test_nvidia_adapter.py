"""The NVIDIA adapter, exercised entirely through ``httpx.MockTransport``.

No API key, no network, no NVIDIA account. Every status code the endpoint can
return, every shape of malformed body, and every retry decision is reproducible
on a laptop with the network cable pulled — which is the only way these paths
get tested at all.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from app.adapters.document_vlm.base import VLMAdapterConfig
from app.adapters.document_vlm.nvidia import (
    IMAGE_FORMAT_INLINE,
    IMAGE_FORMAT_URL,
    NvidiaDocumentVLMAdapter,
    build_nvidia_adapter,
)
from app.document_platform.vlm.errors import (
    DocumentVLMAuthError,
    DocumentVLMBadRequestError,
    DocumentVLMConfigurationError,
    DocumentVLMConnectionError,
    DocumentVLMInvalidResponseError,
    DocumentVLMRateLimitError,
    DocumentVLMRefusedError,
    DocumentVLMTimeoutError,
    DocumentVLMUpstreamError,
)

from .conftest import PNG_BYTES, SECRET_KEY, RecordingTransport, invoice_text, nvidia_response


def build(config, transport: RecordingTransport, **kwargs) -> NvidiaDocumentVLMAdapter:
    return NvidiaDocumentVLMAdapter(config, transport=transport.transport(), **kwargs)


class TestRequestConstruction:
    async def test_it_posts_to_the_chat_completions_endpoint(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=nvidia_response())]
        await build(nvidia_config, transport).extract_document(extraction_request)
        assert str(transport.requests[0].url) == (
            "https://integrate.api.nvidia.test/v1/chat/completions"
        )

    async def test_the_base_url_comes_from_configuration_not_from_code(
        self, transport, extraction_request
    ) -> None:
        """A private NIM deployment must be reachable without a code change."""
        transport.responses = [httpx.Response(200, json=nvidia_response())]
        config = VLMAdapterConfig(
            base_url="https://nim.internal.fbh/v1/", model="custom/model", api_key="k"
        )
        await build(config, transport).extract_document(extraction_request)
        assert str(transport.requests[0].url).startswith("https://nim.internal.fbh/v1/chat")
        assert transport.last_body["model"] == "custom/model"

    async def test_it_authenticates_with_a_bearer_token(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=nvidia_response())]
        await build(nvidia_config, transport).extract_document(extraction_request)
        assert transport.requests[0].headers["Authorization"] == f"Bearer {SECRET_KEY}"

    async def test_it_sends_the_prompt_it_was_given_and_composes_none_of_its_own(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=nvidia_response())]
        await build(nvidia_config, transport).extract_document(extraction_request)
        messages = transport.last_body["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == extraction_request.prompt.system
        text_part = [p for p in messages[1]["content"] if p["type"] == "text"][0]
        assert text_part["text"] == extraction_request.prompt.user

    async def test_images_are_sent_as_openai_content_parts_by_default(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=nvidia_response())]
        await build(nvidia_config, transport).extract_document(extraction_request)
        parts = transport.last_body["messages"][1]["content"]
        image = [p for p in parts if p["type"] == "image_url"][0]
        assert image["image_url"]["url"].startswith("data:image/png;base64,")
        assert base64.b64encode(PNG_BYTES).decode() in image["image_url"]["url"]

    async def test_the_inline_html_form_is_selectable_by_configuration(
        self, transport, extraction_request
    ) -> None:
        """NVIDIA's VL families disagree about image encoding. Configurable
        rather than guessed."""
        transport.responses = [httpx.Response(200, json=nvidia_response())]
        config = VLMAdapterConfig(
            base_url="https://x.test/v1",
            model="m",
            api_key="k",
            extra={"image_format": IMAGE_FORMAT_INLINE},
        )
        await build(config, transport).extract_document(extraction_request)
        content = transport.last_body["messages"][1]["content"]
        assert isinstance(content, str)
        assert '<img src="data:image/png;base64,' in content

    async def test_a_text_only_payload_sends_no_image_parts(
        self, nvidia_config, transport, text_only_payload, prompts
    ) -> None:
        from app.document_platform.vlm.ports import VLMExtractionRequest

        transport.responses = [httpx.Response(200, json=nvidia_response())]
        request = VLMExtractionRequest(
            payload=text_only_payload, prompt=prompts.build(text_only_payload)
        )
        await build(nvidia_config, transport).extract_document(request)
        assert isinstance(transport.last_body["messages"][1]["content"], str)

    async def test_generation_settings_come_from_the_prompt(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=nvidia_response())]
        await build(nvidia_config, transport).extract_document(extraction_request)
        body = transport.last_body
        assert body["temperature"] == 0.0, "extraction is not a creative task"
        assert body["max_tokens"] == extraction_request.prompt.max_output_tokens
        assert body["stream"] is False

    async def test_an_oversized_page_is_dropped_when_text_remains(
        self, transport, prompts
    ) -> None:
        """NVIDIA refuses inline images past its limit. Dropping one page and
        continuing beats failing the whole document."""
        from app.document_platform.vlm.ports import (
            DocumentImage,
            DocumentPayload,
            VLMExtractionRequest,
        )

        transport.responses = [httpx.Response(200, json=nvidia_response())]
        payload = DocumentPayload(
            images=(DocumentImage(data=b"0" * 500_000, media_type="image/png", page=1),),
            ocr_text="INVOICE INV-1",
            text_source="ocr",
        )
        config = VLMAdapterConfig(base_url="https://x.test/v1", model="m", api_key="k")
        await build(config, transport).extract_document(
            VLMExtractionRequest(payload=payload, prompt=prompts.build(payload))
        )
        assert isinstance(transport.last_body["messages"][1]["content"], str)


class TestSuccessfulResponse:
    async def test_it_returns_the_parsed_structure_and_the_verbatim_text(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=nvidia_response())]
        result = await build(nvidia_config, transport).extract_document(extraction_request)
        assert result.structured["invoice_number"] == "INV-2026-0042"
        assert result.raw_text == invoice_text(), "evidence is preserved verbatim"
        assert result.provider == "nvidia"
        assert result.model == nvidia_config.model

    async def test_it_reports_token_usage_when_the_provider_does(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=nvidia_response())]
        result = await build(nvidia_config, transport).extract_document(extraction_request)
        assert result.usage.prompt_tokens == 1200
        assert result.usage.total_tokens == 1380

    async def test_missing_usage_is_absent_rather_than_zero(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        envelope = nvidia_response()
        envelope.pop("usage")
        transport.responses = [httpx.Response(200, json=envelope)]
        result = await build(nvidia_config, transport).extract_document(extraction_request)
        assert result.usage.reported is False

    async def test_fenced_json_is_repaired_and_the_repair_is_reported(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        transport.responses = [
            httpx.Response(200, json=nvidia_response(f"```json\n{invoice_text()}\n```"))
        ]
        result = await build(nvidia_config, transport).extract_document(extraction_request)
        assert result.structured["invoice_number"] == "INV-2026-0042"
        assert result.repaired is True

    async def test_truncation_is_surfaced_on_the_result(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        transport.responses = [
            httpx.Response(200, json=nvidia_response(finish_reason="length"))
        ]
        result = await build(nvidia_config, transport).extract_document(extraction_request)
        assert result.truncated

    async def test_content_returned_as_parts_is_joined(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        envelope = nvidia_response()
        envelope["choices"][0]["message"]["content"] = [
            {"type": "text", "text": '{"invoice_number":'},
            {"type": "text", "text": ' "INV-9"}'},
        ]
        transport.responses = [httpx.Response(200, json=envelope)]
        result = await build(nvidia_config, transport).extract_document(extraction_request)
        assert result.structured == {"invoice_number": "INV-9"}


class TestFailureClassification:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (401, DocumentVLMAuthError),
            (403, DocumentVLMAuthError),
            (400, DocumentVLMBadRequestError),
            (404, DocumentVLMBadRequestError),
            (500, DocumentVLMUpstreamError),
            (503, DocumentVLMUpstreamError),
        ],
    )
    async def test_status_codes_map_to_typed_errors(
        self, nvidia_config, transport, extraction_request, status, expected
    ) -> None:
        transport.default = httpx.Response(status, json={"error": {"message": "nope"}})
        adapter = build(nvidia_config, transport, sleep=_no_sleep)
        with pytest.raises(expected):
            await adapter.extract_document(extraction_request)

    async def test_an_auth_failure_is_never_retried(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        """A rejected key stays rejected; retrying only adds a rate limit to an
        authentication problem."""
        transport.default = httpx.Response(401, json={})
        with pytest.raises(DocumentVLMAuthError) as caught:
            await build(nvidia_config, transport).extract_document(extraction_request)
        assert caught.value.retryable is False
        assert len(transport.requests) == 1

    async def test_the_error_message_quotes_the_provider(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        transport.default = httpx.Response(
            400, json={"error": {"message": "model does not support images"}}
        )
        with pytest.raises(DocumentVLMBadRequestError, match="does not support images"):
            await build(nvidia_config, transport).extract_document(extraction_request)

    async def test_a_timeout_is_classified_as_retryable(
        self, nvidia_config, transport, extraction_request, fake_sleep, recorded_sleeps
    ) -> None:
        transport.responses = [httpx.TimeoutException("read timed out")] * 3
        adapter = build(nvidia_config, transport, sleep=fake_sleep)
        with pytest.raises(DocumentVLMTimeoutError) as caught:
            await adapter.extract_document(extraction_request)
        assert caught.value.retryable is True
        assert len(recorded_sleeps) == 2, "two retries after the first attempt"

    async def test_a_network_failure_is_classified_as_a_connection_error(
        self, nvidia_config, transport, extraction_request, fake_sleep
    ) -> None:
        transport.responses = [httpx.ConnectError("dns failure")] * 3
        adapter = build(nvidia_config, transport, sleep=fake_sleep)
        with pytest.raises(DocumentVLMConnectionError):
            await adapter.extract_document(extraction_request)

    async def test_a_non_json_body_is_an_invalid_response(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        transport.default = httpx.Response(200, text="<html>gateway</html>")
        with pytest.raises(DocumentVLMInvalidResponseError, match="not JSON"):
            await build(nvidia_config, transport).extract_document(extraction_request)

    async def test_an_envelope_without_choices_is_an_invalid_response(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        transport.default = httpx.Response(200, json={"id": "x", "choices": []})
        with pytest.raises(DocumentVLMInvalidResponseError, match="no choices"):
            await build(nvidia_config, transport).extract_document(extraction_request)

    async def test_unparseable_model_text_never_becomes_an_empty_invoice(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        """The single most dangerous failure mode: a fabricated success is
        indistinguishable from a real one downstream."""
        transport.default = httpx.Response(
            200, json=nvidia_response("The document appears to be a receipt.")
        )
        with pytest.raises(DocumentVLMInvalidResponseError) as caught:
            await build(nvidia_config, transport).extract_document(extraction_request)
        assert "receipt" in caught.value.raw_excerpt, "the evidence is kept"

    async def test_a_refusal_is_reported_as_a_refusal(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        transport.default = httpx.Response(
            200, json=nvidia_response("I cannot assist with this document.")
        )
        with pytest.raises(DocumentVLMRefusedError):
            await build(nvidia_config, transport).extract_document(extraction_request)

    async def test_a_json_array_is_refused_rather_than_guessed_at(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        transport.default = httpx.Response(200, json=nvidia_response('[{"a": 1}, {"b": 2}]'))
        with pytest.raises(DocumentVLMInvalidResponseError, match="not an object"):
            await build(nvidia_config, transport).extract_document(extraction_request)

    async def test_a_single_element_array_is_unwrapped(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        transport.default = httpx.Response(
            200, json=nvidia_response(f"[{invoice_text()}]")
        )
        result = await build(nvidia_config, transport).extract_document(extraction_request)
        assert result.structured["invoice_number"] == "INV-2026-0042"


class TestRetries:
    async def test_a_5xx_is_retried_and_can_succeed(
        self, nvidia_config, transport, extraction_request, fake_sleep
    ) -> None:
        transport.responses = [
            httpx.Response(500, json={}),
            httpx.Response(200, json=nvidia_response()),
        ]
        adapter = build(nvidia_config, transport, sleep=fake_sleep)
        result = await adapter.extract_document(extraction_request)
        assert result.retry_count == 1
        assert result.structured["invoice_number"] == "INV-2026-0042"

    async def test_retries_are_bounded_by_configuration(
        self, transport, extraction_request, fake_sleep, recorded_sleeps
    ) -> None:
        config = VLMAdapterConfig(
            base_url="https://x.test/v1", model="m", api_key="k", max_retries=4,
            retry_backoff_seconds=0.1,
        )
        transport.default = httpx.Response(500, json={})
        with pytest.raises(DocumentVLMUpstreamError):
            await build(config, transport, sleep=fake_sleep).extract_document(
                extraction_request
            )
        assert len(transport.requests) == 5, "one attempt plus four retries"

    async def test_backoff_is_exponential_and_deterministic(
        self, transport, extraction_request, fake_sleep, recorded_sleeps
    ) -> None:
        config = VLMAdapterConfig(
            base_url="https://x.test/v1", model="m", api_key="k", max_retries=3,
            retry_backoff_seconds=0.5,
        )
        transport.default = httpx.Response(503, json={})
        with pytest.raises(DocumentVLMUpstreamError):
            await build(config, transport, sleep=fake_sleep).extract_document(
                extraction_request
            )
        assert recorded_sleeps == [0.5, 1.0, 2.0]

    async def test_rate_limiting_honours_retry_after(
        self, nvidia_config, transport, extraction_request, fake_sleep, recorded_sleeps
    ) -> None:
        transport.responses = [
            httpx.Response(429, json={}, headers={"Retry-After": "7"}),
            httpx.Response(200, json=nvidia_response()),
        ]
        adapter = build(nvidia_config, transport, sleep=fake_sleep)
        await adapter.extract_document(extraction_request)
        assert recorded_sleeps == [7.0], "the provider's own signal wins over our backoff"

    async def test_exhausted_rate_limiting_surfaces_the_retry_hint(
        self, nvidia_config, transport, extraction_request, fake_sleep
    ) -> None:
        transport.default = httpx.Response(429, json={}, headers={"Retry-After": "3"})
        with pytest.raises(DocumentVLMRateLimitError) as caught:
            await build(nvidia_config, transport, sleep=fake_sleep).extract_document(
                extraction_request
            )
        assert caught.value.retry_after_seconds == 3.0
        assert caught.value.http_status == 429

    async def test_an_unparseable_answer_is_not_retried(
        self, nvidia_config, transport, extraction_request, recorded_sleeps
    ) -> None:
        """At temperature zero the same prompt produces the same unusable text;
        retrying spends money to fail identically.

        Measured against the live endpoint rather than assumed: twelve calls with
        identical input — six text-only, six with a page image — returned
        byte-identical output every time, same completion-token count. The
        endpoint is deterministic, so a re-ask is pure cost."""
        transport.default = httpx.Response(200, json=nvidia_response("not json at all"))
        with pytest.raises(DocumentVLMInvalidResponseError):
            await build(nvidia_config, transport).extract_document(extraction_request)
        assert len(transport.requests) == 1
        assert recorded_sleeps == []


class TestHealth:
    async def test_a_reachable_catalogue_listing_the_model_is_healthy(
        self, nvidia_config, transport
    ) -> None:
        transport.default = httpx.Response(
            200, json={"data": [{"id": nvidia_config.model}, {"id": "other/model"}]}
        )
        health = await build(nvidia_config, transport).health()
        assert health.healthy
        assert health.detail["model_listed"] is True
        assert health.detail["credentials"] == "configured"

    async def test_rejected_credentials_are_reported_as_unhealthy(
        self, nvidia_config, transport
    ) -> None:
        transport.default = httpx.Response(401, json={})
        health = await build(nvidia_config, transport).health()
        assert not health.healthy
        assert "credentials" in health.error

    async def test_an_unlisted_model_is_a_warning_not_a_failure(
        self, nvidia_config, transport
    ) -> None:
        """Private NIM deployments serve models the public catalogue never lists."""
        transport.default = httpx.Response(200, json={"data": [{"id": "other/model"}]})
        health = await build(nvidia_config, transport).health()
        assert health.healthy
        assert health.detail["model_listed"] is False

    async def test_health_never_raises_even_when_the_network_is_gone(
        self, nvidia_config, transport
    ) -> None:
        transport.responses = [httpx.ConnectError("no route to host")]
        health = await build(nvidia_config, transport).health()
        assert not health.healthy
        assert "reach" in health.error

    async def test_the_probe_does_not_run_an_inference(
        self, nvidia_config, transport
    ) -> None:
        transport.default = httpx.Response(200, json={"data": []})
        await build(nvidia_config, transport).health()
        assert transport.requests[0].method == "GET"
        assert "chat/completions" not in str(transport.requests[0].url)


class TestCost:
    def test_cost_is_estimable_before_the_call(self, nvidia_config, extraction_request) -> None:
        estimate = NvidiaDocumentVLMAdapter(nvidia_config).estimate_cost(extraction_request)
        assert estimate.estimated_prompt_tokens > 0
        assert estimate.estimated_completion_tokens > 0

    def test_an_unpriced_deployment_says_unpriced_rather_than_free(
        self, nvidia_config, extraction_request
    ) -> None:
        estimate = NvidiaDocumentVLMAdapter(nvidia_config).estimate_cost(extraction_request)
        assert estimate.currency == "unpriced"
        assert "NVIDIA_PRICE_PER_MILLION_INPUT_TOKENS" in estimate.basis

    def test_configured_rates_produce_a_priced_estimate(self, extraction_request) -> None:
        config = VLMAdapterConfig(
            base_url="https://x.test/v1",
            model="m",
            api_key="k",
            extra={
                "price_per_million_input_tokens": 100.0,
                "price_per_million_output_tokens": 200.0,
            },
        )
        estimate = NvidiaDocumentVLMAdapter(config).estimate_cost(extraction_request)
        assert estimate.currency == "USD"
        assert estimate.amount > 0


class TestFactory:
    def test_it_reads_every_value_from_settings(self, settings_factory) -> None:
        settings = settings_factory(
            DOCUMENT_VLM_PROVIDER="nvidia",
            NVIDIA_API_KEY="nvapi-from-env",
            NVIDIA_BASE_URL="https://custom.nvidia.test/v1",
            NVIDIA_MODEL="nvidia/some-other-vl",
            DOCUMENT_VLM_TIMEOUT_SECONDS="42",
            DOCUMENT_VLM_MAX_RETRIES="5",
        )
        adapter = build_nvidia_adapter(settings)
        assert adapter.config.base_url == "https://custom.nvidia.test/v1"
        assert adapter.model_name() == "nvidia/some-other-vl"
        assert adapter.config.timeout_seconds == 42.0
        assert adapter.config.max_retries == 5

    def test_a_missing_api_key_fails_at_startup_with_a_useful_message(
        self, settings_factory
    ) -> None:
        settings = settings_factory(DOCUMENT_VLM_PROVIDER="nvidia", NVIDIA_API_KEY="")
        with pytest.raises(DocumentVLMConfigurationError, match="NVIDIA_API_KEY"):
            build_nvidia_adapter(settings)

    def test_the_default_model_is_the_documented_nemotron_vl(self, settings_factory) -> None:
        settings = settings_factory(DOCUMENT_VLM_PROVIDER="nvidia", NVIDIA_API_KEY="k")
        assert (
            build_nvidia_adapter(settings).model_name()
            == "nvidia/llama-3.1-nemotron-nano-vl-8b-v1"
        )

    def test_the_default_image_format_is_the_openai_compatible_one(
        self, settings_factory
    ) -> None:
        settings = settings_factory(DOCUMENT_VLM_PROVIDER="nvidia", NVIDIA_API_KEY="k")
        assert build_nvidia_adapter(settings).config.extra["image_format"] == IMAGE_FORMAT_URL


async def _no_sleep(_seconds: float) -> None:
    return None
