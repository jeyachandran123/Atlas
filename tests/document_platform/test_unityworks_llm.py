"""The document workspace's LLM provider — the one that answers and generates.

This is the seam behind every text call the Document Intelligence Platform
makes: document Q&A, the Excel/Word/PDF generation planner, workspace summaries
and conversation titles all resolve through ``get_llm_provider()``.

Two properties carry the weight here:

* **A slow endpoint must fail, not hang.** The provider this replaced streamed
  with ``read=None``, so a model that stalled left the UI on "Generating
  answer…" indefinitely. A read timeout that raises is the whole point.
* **Failures must stay retryable.** The reasoning engine retries on
  ``LLMProviderError``; anything else escapes as a 500 and burns the turn.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.document_platform.conversation.llm import (
    STREAM_SLICE,
    LLMProviderError,
    StreamStats,
    UnityWorksLLMProvider,
    get_llm_provider,
)
from app.document_platform.conversation.prompts import StructuredPrompt

API_KEY = "uw-llm-secret-do-not-log"  # noqa: S105 - a fixture, not a credential
PREDICT_URL = "https://8001-dep-test.cloudspaces.litng.test/predict"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        unityworks_base_url=PREDICT_URL,
        unityworks_api_key=API_KEY,
        unityworks_model="unityworks-vlm",
    )


@pytest.fixture
def prompt() -> StructuredPrompt:
    return StructuredPrompt(
        system="You answer only from the sources.",
        user="What is the invoice total?",
        strategy="grounded",
    )


class Recorder:
    """A scripted httpx transport that keeps what was sent."""

    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        nxt = self.responses.pop(0) if self.responses else httpx.Response(200, json={})
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    @property
    def last_body(self) -> dict:
        import json

        return json.loads(self.requests[-1].content.decode())


def build(settings, *responses) -> tuple[UnityWorksLLMProvider, Recorder]:
    recorder = Recorder(*responses)
    return (
        UnityWorksLLMProvider(settings, transport=recorder.transport()),
        recorder,
    )


class TestRequestShape:
    async def test_it_posts_to_the_configured_url(self, settings, prompt) -> None:
        provider, rec = build(settings, httpx.Response(200, json={"output": "42"}))
        await provider.generate(prompt)
        assert str(rec.requests[0].url) == PREDICT_URL

    async def test_it_authenticates_with_the_x_api_key_header(self, settings, prompt) -> None:
        provider, rec = build(settings, httpx.Response(200, json={"output": "42"}))
        await provider.generate(prompt)
        assert rec.requests[0].headers["X-API-Key"] == API_KEY

    async def test_system_and_user_are_joined_into_one_prompt(self, settings, prompt) -> None:
        """The endpoint takes one string; the platform composes two."""
        provider, rec = build(settings, httpx.Response(200, json={"output": "42"}))
        await provider.generate(prompt)
        sent = rec.last_body["prompt"]
        assert prompt.system in sent
        assert prompt.user in sent

    async def test_it_sends_an_output_budget(self, settings, prompt) -> None:
        """A generation planner that is cut off mid-JSON produces nothing usable."""
        provider, rec = build(settings, httpx.Response(200, json={"output": "42"}))
        await provider.generate(prompt)
        assert rec.last_body["max_new_tokens"] == settings.dip_max_output_tokens


class TestResponseReading:
    async def test_it_reads_the_output_field(self, settings, prompt) -> None:
        provider, _ = build(settings, httpx.Response(200, json={"output": "Total is 305.20"}))
        result = await provider.generate(prompt)
        assert result.text == "Total is 305.20"
        assert result.provider == "unityworks"
        assert result.model == "unityworks-vlm"

    async def test_it_strips_reasoning_blocks(self, settings, prompt) -> None:
        """A reasoning model's scratchpad is not part of the answer."""
        provider, _ = build(
            settings,
            httpx.Response(200, json={"output": "<think>hmm, let me add</think>Total is 305.20"}),
        )
        result = await provider.generate(prompt)
        assert result.text == "Total is 305.20"

    async def test_a_missing_output_field_is_a_retryable_error(self, settings, prompt) -> None:
        provider, _ = build(settings, httpx.Response(200, json={"unexpected": "shape"}))
        with pytest.raises(LLMProviderError):
            await provider.generate(prompt)


class TestFailuresStayRetryable:
    """The reasoning engine retries LLMProviderError and nothing else."""

    @pytest.mark.parametrize("status", [401, 429, 500, 503])
    async def test_http_errors_become_provider_errors(self, settings, prompt, status) -> None:
        provider, _ = build(settings, httpx.Response(status, json={"detail": "nope"}))
        with pytest.raises(LLMProviderError):
            await provider.generate(prompt)

    async def test_a_timeout_raises_rather_than_hanging(self, settings, prompt) -> None:
        """The bug this provider replaces: read=None left the UI spinning forever."""
        provider, _ = build(settings, httpx.ReadTimeout("too slow"))
        with pytest.raises(LLMProviderError):
            await provider.generate(prompt)

    async def test_an_unreachable_deployment_raises(self, settings, prompt) -> None:
        provider, _ = build(settings, httpx.ConnectError("no route"))
        with pytest.raises(LLMProviderError):
            await provider.generate(prompt)

    async def test_a_timeout_message_names_the_provider_not_the_key(self, settings, prompt) -> None:
        provider, _ = build(settings, httpx.ReadTimeout("too slow"))
        with pytest.raises(LLMProviderError) as caught:
            await provider.generate(prompt)
        assert API_KEY not in str(caught.value)


class TestStreaming:
    async def test_a_one_shot_answer_is_emitted_in_slices(self, settings, prompt) -> None:
        """The endpoint answers in one blob; the UI needs progressive output."""
        answer = "y" * (STREAM_SLICE * 3)
        provider, _ = build(settings, httpx.Response(200, json={"output": answer}))
        stats = StreamStats()

        chunks = [chunk async for chunk in provider.stream(prompt, stats)]

        assert len(chunks) == 3
        assert "".join(chunks) == answer

    async def test_the_stream_reports_what_it_produced(self, settings, prompt) -> None:
        provider, _ = build(settings, httpx.Response(200, json={"output": "Total is 305.20"}))
        stats = StreamStats()

        [chunk async for chunk in provider.stream(prompt, stats)]

        assert stats.full_text == "Total is 305.20"
        assert stats.latency_ms >= 0

    async def test_an_empty_answer_yields_nothing(self, settings, prompt) -> None:
        provider, _ = build(settings, httpx.Response(200, json={"output": ""}))
        stats = StreamStats()
        assert [chunk async for chunk in provider.stream(prompt, stats)] == []

    async def test_a_failing_stream_raises_a_provider_error(self, settings, prompt) -> None:
        provider, _ = build(settings, httpx.ReadTimeout("too slow"))
        stats = StreamStats()
        with pytest.raises(LLMProviderError):
            [chunk async for chunk in provider.stream(prompt, stats)]


class TestSelection:
    def test_the_platform_resolves_to_unityworks(self, monkeypatch, settings) -> None:
        monkeypatch.setattr("app.config.get_settings", lambda: settings, raising=False)
        assert get_llm_provider().name == "unityworks"

    def test_an_unknown_provider_falls_back_rather_than_raising(self) -> None:
        """A misconfigured name must not take the workspace down with it.

        This used to raise. Raising meant one wrong value in the environment
        turned every question in the document workspace into an error, which is
        a worse outcome than quietly answering with the self-hosted model and
        saying so in the log.
        """
        provider = get_llm_provider("ollama")
        assert provider.name == "unityworks"

    def test_ollama_is_no_longer_a_configurable_document_provider(self) -> None:
        """The document workspace runs on UnityWorks alone, by configuration."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Settings(_env_file=None, dip_llm_provider="ollama")

    def test_a_missing_url_fails_with_a_usable_message(self) -> None:
        blank = Settings(_env_file=None, unityworks_base_url="")
        with pytest.raises(LLMProviderError, match="UNITYWORKS_BASE_URL"):
            UnityWorksLLMProvider(blank)
