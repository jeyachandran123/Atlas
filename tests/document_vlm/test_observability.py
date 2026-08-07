"""Telemetry: everything worth knowing, and no credential anywhere.

The redaction tests are the ones that matter most. A key that reaches a log
aggregator is readable by everyone with dashboard access, survives in backups
after it is rotated, and cannot be un-logged. So the assertions here are
deliberately paranoid: the key must be absent from the record, from the log
fields, from every error the adapter can raise, and from the health endpoint's
detail — under a key name that names it, under one that does not, and nested
inside a structure.
"""

from __future__ import annotations

import httpx
import pytest

from app.adapters.document_vlm.nvidia import NvidiaDocumentVLMAdapter
from app.document_platform.vlm.errors import DocumentVLMAuthError, DocumentVLMError
from app.document_platform.vlm.observability import (
    REDACTED,
    VLMCallRecord,
    record_extraction,
    record_retry,
    record_stage,
    record_vlm_call,
    redact,
    safe_url,
)

from .conftest import SECRET_KEY, RecordingTransport, nvidia_response


class TestRedaction:
    @pytest.mark.parametrize(
        "key",
        ["api_key", "apiKey", "API-KEY", "secret", "token", "authorization", "Password"],
    )
    def test_credential_shaped_keys_are_removed_however_they_are_spelled(self, key) -> None:
        assert redact({key: SECRET_KEY})[key] == REDACTED

    def test_credential_shaped_values_are_removed_under_innocent_keys(self) -> None:
        """A key pasted into a "note" field is still a key."""
        assert redact({"note": f"using {SECRET_KEY} today"})["note"] == f"using {REDACTED} today"

    @pytest.mark.parametrize(
        "value",
        [
            "nvapi-abcdefghijklmnop",
            "sk-abcdefghijklmnopqrstuvwx",
            "Bearer abcdefgh.ijklmnop",
            "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4",
        ],
    )
    def test_known_credential_formats_are_caught_by_shape(self, value) -> None:
        assert REDACTED in redact({"detail": value})["detail"]

    def test_nested_structures_are_redacted(self) -> None:
        payload = {"outer": {"headers": [{"authorization": SECRET_KEY}]}}
        assert redact(payload)["outer"]["headers"][0]["authorization"] == REDACTED

    def test_redaction_is_bounded_and_cannot_hang_on_deep_structures(self) -> None:
        deep: dict = {}
        node = deep
        for _ in range(50):
            node["next"] = {}
            node = node["next"]
        assert redact(deep) is not None

    def test_ordinary_values_survive(self) -> None:
        assert redact({"model": "qwen2.5vl:7b", "latency_ms": 12.5}) == {
            "model": "qwen2.5vl:7b",
            "latency_ms": 12.5,
        }

    def test_query_strings_are_stripped_from_endpoints(self) -> None:
        """Some providers accept credentials as query parameters."""
        assert safe_url("https://api.test/v1/chat?api_key=abc") == "https://api.test/v1/chat"


class TestCallRecord:
    def test_the_record_carries_what_operations_needs(self) -> None:
        record = VLMCallRecord(
            provider="nvidia",
            model="nvidia/vl",
            request_id="req-1",
            prompt_id="invoice.extract",
            prompt_version="1.0.0",
            latency_ms=1234.5,
            retry_count=2,
            prompt_tokens=1200,
            completion_tokens=180,
            total_tokens=1380,
            json_strategy="fenced",
            json_repaired=True,
            image_count=3,
            image_bytes=90_000,
            text_chars=4200,
            endpoint="https://integrate.api.nvidia.test/v1/chat/completions",
        )
        fields = record.as_log_fields()
        assert fields["provider"] == "nvidia"
        assert fields["prompt"] == "invoice.extract@1.0.0"
        assert fields["retry_count"] == 2
        assert fields["prompt_tokens"] == 1200
        assert fields["json_strategy"] == "fenced"
        assert fields["image_count"] == 3

    def test_unreported_tokens_are_omitted_rather_than_zeroed(self) -> None:
        fields = VLMCallRecord(provider="ollama", model="m").as_log_fields()
        assert "prompt_tokens" not in fields

    def test_a_secret_in_the_context_never_reaches_the_log_fields(self) -> None:
        record = VLMCallRecord(
            provider="nvidia", model="m", context={"api_key": SECRET_KEY, "region": "sg"}
        )
        fields = record.as_log_fields()
        assert SECRET_KEY not in str(fields)
        assert fields["region"] == "sg"

    def test_an_endpoint_with_a_credential_query_is_cleaned(self) -> None:
        record = VLMCallRecord(
            provider="p", model="m", endpoint="https://api.test/v1?token=abcdefghijkl"
        )
        assert "token=" not in record.as_log_fields()["endpoint"]


class TestEmission:
    def test_recording_never_raises(self) -> None:
        """Telemetry that can fail a request is worse than no telemetry."""
        record_vlm_call(VLMCallRecord(provider="p", model="m", outcome="success"))
        record_vlm_call(
            VLMCallRecord(provider="p", model="m", outcome="error", error_code="vlm_timeout")
        )
        record_retry("p", "m", "vlm_upstream_error")
        record_stage("vlm", "p", 0.25)
        record_extraction("invoice", "p", "success")

    def test_metrics_are_incremented(self) -> None:
        from prometheus_client import REGISTRY

        before = REGISTRY.get_sample_value(
            "document_vlm_requests_total",
            {"provider": "metrics-test", "model": "m", "outcome": "success", "error_code": "none"},
        ) or 0.0
        record_vlm_call(VLMCallRecord(provider="metrics-test", model="m", latency_ms=10.0))
        after = REGISTRY.get_sample_value(
            "document_vlm_requests_total",
            {"provider": "metrics-test", "model": "m", "outcome": "success", "error_code": "none"},
        )
        assert after == before + 1

    def test_retries_are_counted_by_the_failure_class_that_caused_them(self) -> None:
        from prometheus_client import REGISTRY

        record_retry("retry-test", "m", "vlm_rate_limited")
        assert REGISTRY.get_sample_value(
            "document_vlm_retries_total",
            {"provider": "retry-test", "model": "m", "reason": "vlm_rate_limited"},
        )


class TestAdapterNeverLeaksCredentials:
    def test_the_config_repr_hides_the_key(self, nvidia_config) -> None:
        """A dataclass that prints its own fields will eventually print this one
        into a stack trace."""
        assert SECRET_KEY not in repr(nvidia_config)
        assert "api_key=set" in repr(nvidia_config)

    async def test_an_auth_error_names_the_problem_without_the_key(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        transport.default = httpx.Response(401, json={"error": {"message": "invalid key"}})
        adapter = NvidiaDocumentVLMAdapter(nvidia_config, transport=transport.transport())
        with pytest.raises(DocumentVLMAuthError) as caught:
            await adapter.extract_document(extraction_request)
        rendered = f"{caught.value.message} {caught.value.to_dict()} {caught.value!r}"
        assert SECRET_KEY not in rendered
        assert "API key" in caught.value.message, "the operator still learns what to fix"

    async def test_health_detail_reports_presence_not_value(
        self, nvidia_config, transport
    ) -> None:
        transport.default = httpx.Response(200, json={"data": []})
        adapter = NvidiaDocumentVLMAdapter(nvidia_config, transport=transport.transport())
        health = await adapter.health()
        assert SECRET_KEY not in str(health.as_dict())
        assert health.detail["credentials"] == "configured"

    async def test_a_successful_result_carries_no_credential(
        self, nvidia_config, transport, extraction_request
    ) -> None:
        transport.default = httpx.Response(200, json=nvidia_response())
        adapter = NvidiaDocumentVLMAdapter(nvidia_config, transport=transport.transport())
        result = await adapter.extract_document(extraction_request)
        assert SECRET_KEY not in str(result)

    async def test_every_error_type_survives_serialisation_without_the_key(
        self, nvidia_config, extraction_request
    ) -> None:
        for status in (400, 401, 403, 429, 500, 503):
            transport = RecordingTransport(
                default=httpx.Response(status, json={"error": {"message": "x"}})
            )
            adapter = NvidiaDocumentVLMAdapter(
                nvidia_config, transport=transport.transport(), sleep=_no_sleep
            )
            try:
                await adapter.extract_document(extraction_request)
            except DocumentVLMError as exc:
                assert SECRET_KEY not in str(exc.to_dict())


async def _no_sleep(_seconds: float) -> None:
    return None
