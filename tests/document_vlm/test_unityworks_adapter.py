"""The UnityWorks adapter, exercised entirely through ``httpx.MockTransport``.

The endpoint this speaks to is a self-hosted LitServe deployment with a shape
unlike either existing provider: one ``prompt`` string instead of a message
list, one ``image_url`` instead of a content array, an ``X-API-Key`` header
instead of a bearer token, and a bare ``{"output": ...}`` envelope that reports
no token usage at all.

Two properties get the most attention here, because they are the ones this
provider's shape puts at risk:

* **One image per call.** The port hands an adapter up to four page images.
  This endpoint accepts one, so pages are stitched into a single tall image —
  a pixel operation, carrying no interpretation of what the pages mean (V3).
* **Usage is absent, not zero.** A provider that reports nothing must say so;
  zeros would flow into a cost dashboard as fact.
"""

from __future__ import annotations

import base64
import io

import httpx
import pytest

from app.adapters.document_vlm.base import VLMAdapterConfig
from app.adapters.document_vlm.registry import build_document_vlm, registered_providers
from app.adapters.document_vlm.unityworks import (
    UnityWorksDocumentVLMAdapter,
    build_unityworks_adapter,
    describe_unityworks_config,
)
from app.document_platform.vlm.errors import (
    DocumentVLMAuthError,
    DocumentVLMBadRequestError,
    DocumentVLMInvalidResponseError,
    DocumentVLMRateLimitError,
    DocumentVLMTimeoutError,
    DocumentVLMUpstreamError,
)
from app.document_platform.vlm.ports import (
    DocumentImage,
    DocumentPayload,
    VLMExtractionRequest,
    is_document_vlm,
)

from .conftest import PNG_BYTES, RecordingTransport, invoice_text

API_KEY = "uw-test-secret-key-do-not-log"  # noqa: S105 - a fixture, not a credential
PREDICT_URL = "https://8001-dep-test.cloudspaces.litng.test/predict"


def uw_response(content: str = "") -> dict:
    """The endpoint's envelope: one key, no usage, no finish reason."""
    return {"output": content or invoice_text()}


@pytest.fixture
def uw_config() -> VLMAdapterConfig:
    return VLMAdapterConfig(
        base_url=PREDICT_URL,
        model="unityworks-vlm",
        api_key=API_KEY,
        timeout_seconds=30.0,
        max_retries=2,
        retry_backoff_seconds=0.01,
    )


def build(config, transport: RecordingTransport, **kwargs) -> UnityWorksDocumentVLMAdapter:
    return UnityWorksDocumentVLMAdapter(config, transport=transport.transport(), **kwargs)


def real_png(width: int, height: int, colour: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    """A PNG Pillow can actually decode — the stitcher needs real pixels."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def decode_data_uri(uri: str) -> bytes:
    assert uri.startswith("data:"), f"not a data URI: {uri[:40]}"
    return base64.b64decode(uri.split(",", 1)[1])


def request_for(*images: DocumentImage, ocr_text: str = "INVOICE 42") -> VLMExtractionRequest:
    from app.document_platform.vlm.prompts import InvoiceExtractionPromptProvider

    payload = DocumentPayload(
        images=tuple(images),
        ocr_text=ocr_text,
        filename="invoice.pdf",
        media_type="application/pdf",
        page_count=max(1, len(images)),
        text_source="ocr",
    )
    return VLMExtractionRequest(
        payload=payload,
        prompt=InvoiceExtractionPromptProvider().build(payload),
        request_id="req-uw-1",
    )


class TestRequestConstruction:
    async def test_it_posts_to_the_configured_url_verbatim(
        self, uw_config, transport, extraction_request
    ) -> None:
        """The deployment URL is the whole endpoint — nothing is appended to it."""
        transport.responses = [httpx.Response(200, json=uw_response())]
        await build(uw_config, transport).extract_document(extraction_request)
        assert str(transport.requests[0].url) == PREDICT_URL

    async def test_it_authenticates_with_the_x_api_key_header(
        self, uw_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=uw_response())]
        await build(uw_config, transport).extract_document(extraction_request)
        assert transport.requests[0].headers["X-API-Key"] == API_KEY

    async def test_it_sends_the_prompt_it_was_given_and_composes_none_of_its_own(
        self, uw_config, transport, extraction_request
    ) -> None:
        """V5 — an adapter that writes its own prompt owns extraction quality."""
        transport.responses = [httpx.Response(200, json=uw_response())]
        await build(uw_config, transport).extract_document(extraction_request)

        sent = transport.last_body["prompt"]
        assert extraction_request.prompt.system in sent
        assert extraction_request.prompt.user in sent

    async def test_it_forwards_the_ocr_text_alongside_the_pixels(
        self, uw_config, transport
    ) -> None:
        transport.responses = [httpx.Response(200, json=uw_response())]
        request = request_for(
            DocumentImage(data=PNG_BYTES, media_type="image/png", page=1),
            ocr_text="TOTAL DUE 305.20",
        )
        await build(uw_config, transport).extract_document(request)
        assert "TOTAL DUE 305.20" in transport.last_body["prompt"]

    async def test_it_sends_the_image_as_a_data_uri(
        self, uw_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=uw_response())]
        await build(uw_config, transport).extract_document(extraction_request)

        image_url = transport.last_body["image_url"]
        assert image_url.startswith("data:image/png;base64,")
        assert decode_data_uri(image_url) == PNG_BYTES

    async def test_it_caps_output_at_the_prompts_token_budget(
        self, uw_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=uw_response())]
        await build(uw_config, transport).extract_document(extraction_request)
        assert transport.last_body["max_new_tokens"] == (
            extraction_request.prompt.max_output_tokens
        )

    async def test_a_text_only_document_sends_no_image_key(
        self, uw_config, transport, text_only_payload, prompts
    ) -> None:
        """A PDF with a text layer has no pixels; the key is omitted, not null."""
        transport.responses = [httpx.Response(200, json=uw_response())]
        request = VLMExtractionRequest(
            payload=text_only_payload, prompt=prompts.build(text_only_payload)
        )
        await build(uw_config, transport).extract_document(request)
        assert "image_url" not in transport.last_body


class TestMultiPageStitching:
    async def test_three_pages_become_exactly_one_image(self, uw_config, transport) -> None:
        """The endpoint takes one image; the port may hand over four."""
        transport.responses = [httpx.Response(200, json=uw_response())]
        request = request_for(
            DocumentImage(data=real_png(40, 50), media_type="image/png", page=1),
            DocumentImage(data=real_png(40, 60), media_type="image/png", page=2),
            DocumentImage(data=real_png(40, 70), media_type="image/png", page=3),
        )
        await build(uw_config, transport).extract_document(request)

        body = transport.last_body
        assert isinstance(body["image_url"], str), "one image, not a list"
        assert len(transport.requests) == 1, "one call, not one per page"

    async def test_the_stitched_image_keeps_every_page(self, uw_config, transport) -> None:
        """Height is the sum — a stitch that drops a page loses an invoice line."""
        from PIL import Image

        transport.responses = [httpx.Response(200, json=uw_response())]
        request = request_for(
            DocumentImage(data=real_png(40, 50), media_type="image/png", page=1),
            DocumentImage(data=real_png(40, 60), media_type="image/png", page=2),
        )
        await build(uw_config, transport).extract_document(request)

        stitched = Image.open(io.BytesIO(decode_data_uri(transport.last_body["image_url"])))
        assert stitched.width == 40
        assert stitched.height == 110

    async def test_pages_of_different_widths_are_scaled_to_a_common_width(
        self, uw_config, transport
    ) -> None:
        from PIL import Image

        transport.responses = [httpx.Response(200, json=uw_response())]
        request = request_for(
            DocumentImage(data=real_png(100, 50), media_type="image/png", page=1),
            DocumentImage(data=real_png(50, 50), media_type="image/png", page=2),
        )
        await build(uw_config, transport).extract_document(request)

        stitched = Image.open(io.BytesIO(decode_data_uri(transport.last_body["image_url"])))
        assert stitched.width == 100
        # Page 2 doubles in width, so its height doubles too: 50 + 100.
        assert stitched.height == 150

    async def test_a_single_page_is_sent_untouched(self, uw_config, transport) -> None:
        """No re-encode for the common case — re-encoding only loses fidelity."""
        transport.responses = [httpx.Response(200, json=uw_response())]
        original = real_png(40, 50)
        request = request_for(DocumentImage(data=original, media_type="image/png", page=1))
        await build(uw_config, transport).extract_document(request)

        assert decode_data_uri(transport.last_body["image_url"]) == original

    async def test_undecodable_pages_raise_rather_than_silently_dropping_one(
        self, uw_config, transport
    ) -> None:
        """V2 — sending page 1 alone and calling it the document is fabrication."""
        transport.responses = [httpx.Response(200, json=uw_response())]
        request = request_for(
            DocumentImage(data=PNG_BYTES, media_type="image/png", page=1),
            DocumentImage(data=PNG_BYTES, media_type="image/png", page=2),
        )
        with pytest.raises(DocumentVLMBadRequestError, match="could not be combined"):
            await build(uw_config, transport).extract_document(request)


class TestResponseReading:
    async def test_it_parses_the_output_field(
        self, uw_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=uw_response())]
        result = await build(uw_config, transport).extract_document(extraction_request)
        assert result.structured["invoice_number"] == "INV-2026-0042"
        assert result.provider == "unityworks"

    async def test_it_preserves_the_raw_text_next_to_the_structured_answer(
        self, uw_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json=uw_response())]
        result = await build(uw_config, transport).extract_document(extraction_request)
        assert result.raw_text == invoice_text()

    async def test_unreported_usage_stays_unreported_rather_than_becoming_zero(
        self, uw_config, transport, extraction_request
    ) -> None:
        """A zero that means "not reported" is a lie in a cost dashboard."""
        transport.responses = [httpx.Response(200, json=uw_response())]
        result = await build(uw_config, transport).extract_document(extraction_request)
        assert result.usage.reported is False
        assert result.usage.prompt_tokens is None

    async def test_a_missing_output_key_is_an_error_not_an_empty_invoice(
        self, uw_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(200, json={"unexpected": "shape"})]
        with pytest.raises(DocumentVLMInvalidResponseError):
            await build(uw_config, transport).extract_document(extraction_request)

    async def test_prose_instead_of_json_is_an_error(
        self, uw_config, transport, extraction_request
    ) -> None:
        transport.responses = [
            httpx.Response(200, json=uw_response("I think this is an invoice for about $300."))
        ]
        with pytest.raises(DocumentVLMInvalidResponseError):
            await build(uw_config, transport).extract_document(extraction_request)


class TestFailureModes:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (401, DocumentVLMAuthError),
            (403, DocumentVLMAuthError),
            (429, DocumentVLMRateLimitError),
            (500, DocumentVLMUpstreamError),
            (400, DocumentVLMBadRequestError),
        ],
    )
    async def test_status_codes_map_to_typed_errors(
        self, uw_config, transport, extraction_request, status, expected
    ) -> None:
        transport.responses = [httpx.Response(status, json={"error": "nope"})] * 4
        with pytest.raises(expected):
            await build(uw_config, transport).extract_document(extraction_request)

    async def test_a_timeout_is_a_typed_error_never_an_empty_result(
        self, uw_config, transport, extraction_request, fake_sleep
    ) -> None:
        """V2 — the failure mode that matters most for a cold-starting endpoint."""
        transport.responses = [httpx.TimeoutException("timed out")] * 4
        with pytest.raises(DocumentVLMTimeoutError):
            await build(uw_config, transport, sleep=fake_sleep).extract_document(extraction_request)

    async def test_it_retries_a_cold_start_then_succeeds(
        self, uw_config, transport, extraction_request, fake_sleep, recorded_sleeps
    ) -> None:
        """A sleeping cloudspace 503s before it wakes; that is worth retrying."""
        transport.responses = [
            httpx.Response(503, json={"error": "starting"}),
            httpx.Response(200, json=uw_response()),
        ]
        result = await build(uw_config, transport, sleep=fake_sleep).extract_document(
            extraction_request
        )
        assert result.structured["invoice_number"] == "INV-2026-0042"
        assert result.retry_count == 1
        assert recorded_sleeps == [0.01]

    async def test_it_does_not_retry_a_rejected_key(
        self, uw_config, transport, extraction_request, fake_sleep
    ) -> None:
        transport.responses = [httpx.Response(401, json={"error": "bad key"})] * 4
        with pytest.raises(DocumentVLMAuthError):
            await build(uw_config, transport, sleep=fake_sleep).extract_document(extraction_request)
        assert len(transport.requests) == 1, "a rejected key cannot succeed on retry"


class TestCredentialsNeverLeak:
    """V7 — the key appears in exactly one place: the outgoing header."""

    def test_the_config_repr_does_not_print_the_key(self, uw_config) -> None:
        assert API_KEY not in repr(uw_config)

    def test_the_adapter_repr_does_not_print_the_key(self, uw_config, transport) -> None:
        assert API_KEY not in repr(build(uw_config, transport))

    async def test_an_auth_error_does_not_quote_the_key(
        self, uw_config, transport, extraction_request
    ) -> None:
        transport.responses = [httpx.Response(401, json={"error": f"invalid key {API_KEY}"})]
        with pytest.raises(DocumentVLMAuthError) as caught:
            await build(uw_config, transport).extract_document(extraction_request)
        assert API_KEY not in str(caught.value)

    async def test_health_detail_does_not_carry_the_key(self, uw_config, transport) -> None:
        transport.responses = [httpx.Response(200, json=uw_response("ok"))]
        health = await build(uw_config, transport).health()
        assert API_KEY not in str(health.as_dict())

    def test_describe_reports_only_whether_a_key_is_set(self, settings_factory) -> None:
        settings = settings_factory(UNITYWORKS_BASE_URL=PREDICT_URL, UNITYWORKS_API_KEY=API_KEY)
        described = describe_unityworks_config(settings)
        assert described["api_key_configured"] is True
        assert API_KEY not in str(described)


class TestHealth:
    async def test_the_probe_asks_for_a_single_token(self, uw_config, transport) -> None:
        """The endpoint has no catalogue to ask, so the probe is an inference —
        kept to one token so a health poll is not a bill."""
        transport.responses = [httpx.Response(200, json=uw_response("ok"))]
        await build(uw_config, transport).health()
        assert transport.last_body["max_new_tokens"] == 1

    async def test_a_serving_endpoint_is_healthy(self, uw_config, transport) -> None:
        transport.responses = [httpx.Response(200, json=uw_response("ok"))]
        health = await build(uw_config, transport).health()
        assert health.healthy is True
        assert health.provider == "unityworks"

    async def test_a_rejected_key_is_unhealthy_rather_than_an_exception(
        self, uw_config, transport
    ) -> None:
        """The blind spot that mattered: health must fail when the key fails."""
        transport.responses = [httpx.Response(401, json={"error": "bad key"})]
        health = await build(uw_config, transport).health()
        assert health.healthy is False

    async def test_an_unreachable_deployment_is_unhealthy_not_a_crash(
        self, uw_config, transport
    ) -> None:
        """Cloudspace URLs expire; health is how an operator finds out."""
        transport.responses = [httpx.ConnectError("no route to host")]
        health = await build(uw_config, transport).health()
        assert health.healthy is False


class TestWiring:
    def test_the_adapter_conforms_to_the_port(self, uw_config, transport) -> None:
        assert is_document_vlm(build(uw_config, transport))

    def test_the_factory_reads_every_value_from_settings(self, settings_factory) -> None:
        settings = settings_factory(
            UNITYWORKS_BASE_URL=PREDICT_URL,
            UNITYWORKS_API_KEY=API_KEY,
            UNITYWORKS_MODEL="my-vlm",
        )
        adapter = build_unityworks_adapter(settings)
        assert adapter.config.base_url == PREDICT_URL
        assert adapter.model_name() == "my-vlm"

    def test_it_is_selectable_by_name(self) -> None:
        assert "unityworks" in registered_providers()

    def test_the_registry_builds_it_when_configured(self, settings_factory) -> None:
        settings = settings_factory(
            DOCUMENT_VLM_PROVIDER="unityworks",
            UNITYWORKS_BASE_URL=PREDICT_URL,
            UNITYWORKS_API_KEY=API_KEY,
        )
        adapter = build_document_vlm(settings=settings)
        assert adapter.provider_name() == "unityworks"

    def test_the_existing_providers_are_still_selectable(self) -> None:
        """Adding a provider must not remove the fallbacks."""
        assert {"nvidia", "ollama"} <= set(registered_providers())

    def test_a_self_hosted_call_is_reported_as_unpriced(
        self, uw_config, transport, extraction_request
    ) -> None:
        estimate = build(uw_config, transport).estimate_cost(extraction_request)
        assert estimate.is_free
        assert estimate.currency == "none"
        assert estimate.estimated_prompt_tokens > 0
