"""The REST surface: ``POST /api/v1/document/extract-invoice`` and its siblings.

The app under test is assembled from the real router with two dependencies
overridden — authentication and the pipeline's provider. No database, no Redis,
no network, and no provider: exactly the arrangement an ERP integrator's CI can
reproduce.

The contract being defended is the one the ERP codes against. Every assertion
about a key name here is an assertion that an integration will not break.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.v1.document_extraction.dependencies import get_extraction_pipeline
from app.api.v1.document_extraction.router import router
from app.auth import get_current_user
from app.document_platform.vlm.errors import (
    DocumentVLMAuthError,
    DocumentVLMRateLimitError,
    DocumentVLMTimeoutError,
    DocumentVLMUnavailableError,
)
from app.document_platform.vlm.pipeline import DocumentExtractionPipeline

from .conftest import PNG_BYTES, ScriptedDocumentVLM


class _FakeUser:
    id = "user-1"
    org_id = "org-1"
    role = "developer"


@pytest.fixture
def vlm() -> ScriptedDocumentVLM:
    return ScriptedDocumentVLM(provider="scripted", model="scripted-vlm-1")


@pytest.fixture
def app(vlm: ScriptedDocumentVLM) -> FastAPI:
    application = FastAPI()
    application.include_router(router, prefix="/api/v1")
    application.dependency_overrides[get_current_user] = lambda: _FakeUser()
    application.dependency_overrides[get_extraction_pipeline] = (
        lambda: DocumentExtractionPipeline(vlm)
    )
    return application


@pytest.fixture
async def client(app: FastAPI):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client


def upload(content: bytes = PNG_BYTES, name: str = "invoice.png", mime: str = "image/png"):
    return {"file": (name, content, mime)}


class TestExtractInvoice:
    async def test_the_endpoint_is_where_the_contract_says_it_is(self, client) -> None:
        response = await client.post("/api/v1/document/extract-invoice", files=upload())
        assert response.status_code == 200

    async def test_the_success_envelope_matches_the_contract(self, client) -> None:
        body = (
            await client.post("/api/v1/document/extract-invoice", files=upload())
        ).json()
        assert body["success"] is True
        assert body["provider"] == "scripted"
        assert body["model"] == "scripted-vlm-1"
        assert isinstance(body["processingTime"], int | float)
        assert isinstance(body["data"], dict)

    async def test_the_data_is_the_validated_invoice(self, client) -> None:
        body = (
            await client.post("/api/v1/document/extract-invoice", files=upload())
        ).json()
        data = body["data"]
        assert data["invoice_number"] == "INV-2026-0042"
        assert data["currency"] == "SGD"
        assert len(data["line_items"]) == 2
        assert data["totals"]["grand_total"] == 305.2

    async def test_provenance_travels_with_the_data(self, client) -> None:
        body = (
            await client.post("/api/v1/document/extract-invoice", files=upload())
        ).json()
        assert body["promptVersion"] == "1.0.0"
        assert body["schemaVersion"] == "1.0.0"
        assert body["requestId"]
        assert body["document"]["imagesSent"] == 1
        assert set(body["stages"]) == {"payload", "prompt", "vlm", "validation"}

    async def test_usage_is_reported_when_the_provider_reports_it(self, client) -> None:
        body = (
            await client.post("/api/v1/document/extract-invoice", files=upload())
        ).json()
        assert body["usage"]["promptTokens"] == 100
        assert body["usage"]["totalTokens"] == 150

    async def test_warnings_reach_the_caller(self, client, vlm) -> None:
        vlm.structured = {"invoice_number": "INV-1"}
        body = (
            await client.post("/api/v1/document/extract-invoice", files=upload())
        ).json()
        assert body["success"] is True
        assert any("missing expected field" in w for w in body["warnings"])

    async def test_a_pdf_is_accepted(self, client) -> None:
        pdf = b"%PDF-1.4\n" + b"INVOICE INV-1 total 100.00\n" * 20
        response = await client.post(
            "/api/v1/document/extract-invoice",
            files=upload(pdf, "invoice.pdf", "application/pdf"),
        )
        assert response.status_code in (200, 422), response.text

    async def test_a_prompt_version_can_be_pinned_per_request(self, client, vlm) -> None:
        response = await client.post(
            "/api/v1/document/extract-invoice",
            files=upload(),
            data={"prompt_version": "1.0.0"},
        )
        assert response.status_code == 200
        assert response.json()["promptVersion"] == "1.0.0"

    async def test_the_client_never_learns_which_provider_implementation_ran(
        self, client
    ) -> None:
        """``provider`` is a label for attribution. Nothing in the envelope is
        provider-*shaped*: no NVIDIA choices array, no Ollama eval counts."""
        body = (
            await client.post("/api/v1/document/extract-invoice", files=upload())
        ).json()
        assert "choices" not in body
        assert "eval_count" not in body
        assert set(body["data"]) >= {"invoice_number", "line_items", "totals"}


class TestErrorMapping:
    async def test_an_unsupported_type_is_415(self, client) -> None:
        response = await client.post(
            "/api/v1/document/extract-invoice",
            files=upload(b"PK\x03\x04junk", "notes.docx", "application/octet-stream"),
        )
        assert response.status_code == 415
        body = response.json()
        assert body["success"] is False
        assert body["error"]["code"] == "unsupported_document"

    async def test_an_empty_upload_is_422(self, client) -> None:
        response = await client.post(
            "/api/v1/document/extract-invoice", files=upload(b"", "invoice.pdf", "application/pdf")
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "empty_document"

    async def test_a_provider_timeout_is_504_and_marked_retryable(
        self, client, vlm
    ) -> None:
        vlm.error = DocumentVLMTimeoutError(
            "provider timed out", provider="scripted", model="scripted-vlm-1"
        )
        response = await client.post("/api/v1/document/extract-invoice", files=upload())
        assert response.status_code == 504
        assert response.json()["error"]["retryable"] is True

    async def test_a_provider_auth_failure_is_502_and_not_retryable(
        self, client, vlm
    ) -> None:
        """Never 401: the *caller* authenticated fine. Returning 401 would send
        an ERP chasing its own credentials for our misconfiguration."""
        vlm.error = DocumentVLMAuthError("nvidia rejected the credentials", provider="scripted")
        response = await client.post("/api/v1/document/extract-invoice", files=upload())
        assert response.status_code == 502
        assert response.json()["error"]["retryable"] is False

    async def test_rate_limiting_is_429_with_a_retry_after_header(
        self, client, vlm
    ) -> None:
        vlm.error = DocumentVLMRateLimitError(
            "rate limited", provider="scripted", retry_after_seconds=12.0
        )
        response = await client.post("/api/v1/document/extract-invoice", files=upload())
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "12"

    async def test_an_unavailable_model_is_503(self, client, vlm) -> None:
        vlm.error = DocumentVLMUnavailableError("model not pulled", provider="scripted")
        response = await client.post("/api/v1/document/extract-invoice", files=upload())
        assert response.status_code == 503

    async def test_a_schema_failure_returns_its_violations(self, client, vlm) -> None:
        vlm.structured = {}
        response = await client.post("/api/v1/document/extract-invoice", files=upload())
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "invoice_schema_error"
        assert body["error"]["violations"]

    async def test_every_failure_uses_the_same_envelope(self, client, vlm) -> None:
        """A client reads ``success`` first and never has to guess the shape."""
        vlm.error = DocumentVLMTimeoutError("timeout", provider="scripted")
        body = (
            await client.post("/api/v1/document/extract-invoice", files=upload())
        ).json()
        assert set(body) >= {"success", "provider", "model", "processingTime", "requestId", "error"}
        assert set(body["error"]) >= {"code", "message", "retryable"}

    async def test_a_failure_never_carries_a_data_payload(self, client, vlm) -> None:
        vlm.structured = {}
        body = (
            await client.post("/api/v1/document/extract-invoice", files=upload())
        ).json()
        assert "data" not in body, "an extraction that did not happen must be absent"


class TestAuthentication:
    async def test_the_endpoint_requires_authentication(self, vlm) -> None:
        """Same auth as every other endpoint — JWT or X-API-Key. An ERP uses
        the key; nobody gets an unauthenticated document sink."""
        application = FastAPI()
        application.include_router(router, prefix="/api/v1")
        application.dependency_overrides[get_extraction_pipeline] = (
            lambda: DocumentExtractionPipeline(vlm)
        )
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as unauthenticated:
            response = await unauthenticated.post(
                "/api/v1/document/extract-invoice", files=upload()
            )
        assert response.status_code in (401, 403)


class TestHealthEndpoint:
    async def test_a_healthy_provider_is_200(self, client) -> None:
        response = await client.get("/api/v1/document/vlm/health")
        assert response.status_code == 200
        assert response.json()["healthy"] is True

    async def test_an_unhealthy_provider_is_503(self, client, vlm) -> None:
        """A 200 carrying ``healthy: false`` is invisible to every uptime
        monitor ever built."""
        vlm.healthy = False
        response = await client.get("/api/v1/document/vlm/health")
        assert response.status_code == 503
        assert response.json()["healthy"] is False

    async def test_health_reports_the_bound_model(self, client) -> None:
        body = (await client.get("/api/v1/document/vlm/health")).json()
        assert body["provider"] == "scripted"
        assert body["model"] == "scripted-vlm-1"


class TestProviderEndpoint:
    async def test_it_describes_the_binding(self, client) -> None:
        body = (await client.get("/api/v1/document/vlm/provider")).json()
        assert body["provider"] == "scripted"
        assert body["portVersion"] == "1.0.0"
        assert body["promptId"] == "invoice.extract"
        assert "nvidia" in body["availableProviders"]
        assert "ollama" in body["availableProviders"]

    async def test_it_reports_limits_operators_need(self, client) -> None:
        limits = (await client.get("/api/v1/document/vlm/provider")).json()["limits"]
        assert set(limits) >= {"max_file_size_mb", "max_pages", "timeout_seconds"}

    async def test_it_never_returns_a_credential(self, client) -> None:
        """Presence, not value — the only fact anyone debugging a 401 needs and
        the only one safe to serve over HTTP."""
        raw = (await client.get("/api/v1/document/vlm/provider")).text
        assert "nvapi-" not in raw
        assert "api_key" not in raw.lower() or "apiKeyConfigured" in raw
        assert isinstance((await client.get("/api/v1/document/vlm/provider")).json()[
            "apiKeyConfigured"
        ], bool)


class TestOpenApiContract:
    def test_the_route_is_documented_for_erp_integrators(self, app: FastAPI) -> None:
        schema = app.openapi()
        path = schema["paths"]["/api/v1/document/extract-invoice"]["post"]
        assert path["requestBody"]["content"].get("multipart/form-data")
        assert "200" in path["responses"]
        for status in ("413", "415", "422", "429", "502", "503", "504"):
            assert status in path["responses"], f"undocumented failure mode: {status}"
