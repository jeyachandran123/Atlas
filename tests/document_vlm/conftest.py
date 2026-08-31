"""Fixtures: deterministic doubles for every collaborator a VLM call has.

The centrepiece is ``ScriptedDocumentVLM`` — a full ``DocumentVLMPort``
implementation that answers from a script. It exists for the same reason the
platform's other conformance doubles do: the property under test is *"does the
platform handle what a model said"*, and a real model would make that
non-deterministic while testing nothing about the platform.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from app.adapters.document_vlm.base import VLMAdapterConfig
from app.config import Settings
from app.document_platform.vlm.errors import DocumentVLMError
from app.document_platform.vlm.ports import (
    CostEstimate,
    DocumentImage,
    DocumentPayload,
    ProviderHealth,
    TokenUsage,
    VLMExtractionRequest,
    VLMExtractionResult,
)
from app.document_platform.vlm.prompts import InvoiceExtractionPromptProvider


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "filterwarnings",
        "ignore:The event_loop fixture provided by pytest-asyncio has been "
        "redefined:DeprecationWarning",
    )


@pytest.fixture
def event_loop():
    """Function-scoped loop, shadowing the Atlas root conftest's session-scoped one.

    The same workaround the Vision OS suite documents: these tests have no
    database, no FastAPI lifespan and no session-scoped async state, and
    inheriting a session loop breaks fixture introspection under
    pytest-asyncio 0.24.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── canned documents ─────────────────────────────────────────────────────────

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPEG_BYTES = b"\xff\xd8\xff" + b"0" * 64

VALID_INVOICE_JSON: dict[str, Any] = {
    "document_type": "invoice",
    "invoice_number": "INV-2026-0042",
    "purchase_order_number": "PO-9001",
    "invoice_date": "2026-01-15",
    "due_date": "2026-02-14",
    "currency": "SGD",
    "supplier": {"name": "Acme Supplies Pte Ltd", "tax_id": "M2-1234567-8"},
    "customer": {"name": "FBH Singapore Pte Ltd"},
    "line_items": [
        {"description": "Steel bracket", "quantity": 10, "unit_price": 25.0, "amount": 250.0},
        {"description": "Delivery", "quantity": 1, "unit_price": 30.0, "amount": 30.0},
    ],
    "totals": {
        "subtotal": 280.0,
        "tax_total": 25.2,
        "grand_total": 305.2,
        "amount_due": 305.2,
    },
    "payment_terms": "Net 30",
}


def invoice_text(payload: dict[str, Any] | None = None) -> str:
    return json.dumps(payload if payload is not None else VALID_INVOICE_JSON)


# ── payloads and prompts ─────────────────────────────────────────────────────


@pytest.fixture
def image_payload() -> DocumentPayload:
    return DocumentPayload(
        images=(DocumentImage(data=PNG_BYTES, media_type="image/png", page=1),),
        ocr_text="INVOICE INV-2026-0042\nTotal 305.20",
        filename="invoice.png",
        media_type="image/png",
        page_count=1,
        text_source="ocr",
    )


@pytest.fixture
def text_only_payload() -> DocumentPayload:
    return DocumentPayload(
        ocr_text="INVOICE INV-2026-0042\nTotal 305.20",
        filename="invoice.pdf",
        media_type="application/pdf",
        page_count=1,
        text_source="pdf_text_layer",
    )


@pytest.fixture
def prompts() -> InvoiceExtractionPromptProvider:
    return InvoiceExtractionPromptProvider()


@pytest.fixture
def extraction_request(
    image_payload: DocumentPayload, prompts: InvoiceExtractionPromptProvider
) -> VLMExtractionRequest:
    return VLMExtractionRequest(
        payload=image_payload,
        prompt=prompts.build(image_payload),
        request_id="req-test-1",
    )


# ── adapter configuration ────────────────────────────────────────────────────

SECRET_KEY = "nvapi-test-secret-key-do-not-log"  # noqa: S105 - a fixture, not a credential


@pytest.fixture
def nvidia_config() -> VLMAdapterConfig:
    return VLMAdapterConfig(
        base_url="https://integrate.api.nvidia.test/v1",
        model="nvidia/llama-3.1-nemotron-nano-vl-8b-v1",
        api_key=SECRET_KEY,
        timeout_seconds=30.0,
        max_retries=2,
        retry_backoff_seconds=0.01,
    )


@pytest.fixture
def ollama_config() -> VLMAdapterConfig:
    return VLMAdapterConfig(
        base_url="http://192.168.6.118:11434",
        model="qwen2.5vl:7b",
        timeout_seconds=30.0,
        max_retries=2,
        retry_backoff_seconds=0.01,
    )


@pytest.fixture
def recorded_sleeps() -> list[float]:
    """Collects backoff delays so retry tests assert instead of waiting."""
    return []


@pytest.fixture
def fake_sleep(recorded_sleeps: list[float]):
    async def _sleep(seconds: float) -> None:
        recorded_sleeps.append(seconds)

    return _sleep


# ── HTTP doubles ─────────────────────────────────────────────────────────────


def nvidia_response(
    content: str = "", *, finish_reason: str = "stop", usage: dict[str, int] | None = None
) -> dict[str, Any]:
    """An NVIDIA chat-completion envelope with the given assistant text."""
    return {
        "id": "chatcmpl-test",
        "model": "nvidia/llama-3.1-nemotron-nano-vl-8b-v1",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content or invoice_text()},
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage or {"prompt_tokens": 1200, "completion_tokens": 180, "total_tokens": 1380},
    }


def ollama_response(
    content: str = "", *, done_reason: str = "stop", counts: tuple[int, int] = (900, 150)
) -> dict[str, Any]:
    """An Ollama ``/api/chat`` envelope with the given assistant text."""
    return {
        "model": "qwen2.5vl:7b",
        "message": {"role": "assistant", "content": content or invoice_text()},
        "done": True,
        "done_reason": done_reason,
        "prompt_eval_count": counts[0],
        "eval_count": counts[1],
    }


@dataclass
class RecordingTransport:
    """An ``httpx`` transport that replays scripted responses and keeps requests.

    Sequenced rather than keyed by URL: a retry test needs the *second* call to
    a URL to answer differently from the first, which a URL-keyed double cannot
    express.
    """

    responses: list[httpx.Response | Exception] = field(default_factory=list)
    requests: list[httpx.Request] = field(default_factory=list)
    default: httpx.Response | None = None

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.responses:
            nxt = self.responses.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt
        if self.default is not None:
            return self.default
        return httpx.Response(200, json={})

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content.decode() or "{}") for r in self.requests if r.content]

    @property
    def last_body(self) -> dict[str, Any]:
        return self.bodies[-1]


@pytest.fixture
def transport() -> RecordingTransport:
    return RecordingTransport()


# ── a scripted provider ──────────────────────────────────────────────────────


@dataclass
class ScriptedDocumentVLM:
    """A ``DocumentVLMPort`` that answers from a script. Free and deterministic.

    Structurally conformant — nothing is inherited — which is the point: if a
    plain dataclass with five methods can stand in for NVIDIA everywhere the
    platform touches a model, the port is at the right altitude.
    """

    provider: str = "scripted"
    model: str = "scripted-vlm-1"
    structured: dict[str, Any] = field(default_factory=lambda: dict(VALID_INVOICE_JSON))
    raw_text: str = ""
    error: DocumentVLMError | None = None
    finish_reason: str = "stop"
    repaired: bool = False
    healthy: bool = True
    calls: list[VLMExtractionRequest] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=lambda: TokenUsage(100, 50, 150))

    def provider_name(self) -> str:
        return self.provider

    def model_name(self) -> str:
        return self.model

    async def extract_document(self, request: VLMExtractionRequest) -> VLMExtractionResult:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return VLMExtractionResult(
            structured=dict(self.structured),
            raw_text=self.raw_text or json.dumps(self.structured),
            provider=self.provider,
            model=self.model,
            latency_ms=12.5,
            usage=self.usage,
            request_id=request.request_id,
            finish_reason=self.finish_reason,
            repaired=self.repaired,
            prompt_id=request.prompt.prompt_id,
            prompt_version=request.prompt.version,
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            healthy=self.healthy,
            provider=self.provider,
            model=self.model,
            latency_ms=1.0,
            detail={"scripted": True},
            error="" if self.healthy else "scripted unhealthy",
        )

    def estimate_cost(self, request: VLMExtractionRequest) -> CostEstimate:
        return CostEstimate(
            amount=0.0,
            currency="none",
            estimated_prompt_tokens=100,
            estimated_completion_tokens=request.prompt.max_output_tokens,
            basis="scripted",
        )


@pytest.fixture
def scripted_vlm() -> ScriptedDocumentVLM:
    return ScriptedDocumentVLM()


# ── settings ─────────────────────────────────────────────────────────────────


@pytest.fixture
def settings_factory(monkeypatch: pytest.MonkeyPatch):
    """Build ``Settings`` from an explicit environment, ignoring the repo's .env.

    Reading the developer's own ``.env`` would make "does DOCUMENT_VLM_PROVIDER
    select the provider" depend on what that developer happens to have
    configured, which is the opposite of a test.
    """

    def _factory(**env: str) -> Settings:
        for key, value in env.items():
            monkeypatch.setenv(key.upper(), str(value))
        return Settings(_env_file=None)

    return _factory
