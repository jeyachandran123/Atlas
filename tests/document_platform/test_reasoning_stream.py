"""Streaming had no retries, and that is where the turns actually died.

``ask()`` went through ``ReasoningEngine.generate()`` and shrugged off a
transient failure. ``ask_stream()`` - the path the workspace UI uses - called
the provider directly, so one HTTP 500 from the deployment ended the turn and
the user read "The response could not be generated." Two recorded turns died
exactly that way while the identical question answered fine moments later.

Retrying a stream is only safe while nothing has reached the user. This
provider answers in one shot and slices the result, so a failure lands before
the first chunk and a replay is invisible; once a chunk is out, the turn is
committed to that answer and a replay would print a second answer on top of
half of a first one. Both halves of that rule are asserted here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.document_platform.conversation.llm import (
    AbstractLLMProvider,
    LLMProviderError,
    LLMResult,
    StreamStats,
)
from app.document_platform.conversation.prompts import StructuredPrompt
from app.document_platform.conversation.reasoning import ReasoningEngine, ReasoningError


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine's backoff is real seconds; the behaviour under test is not."""

    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr(
        "app.document_platform.conversation.reasoning.asyncio.sleep", _instant
    )


@pytest.fixture
def prompt() -> StructuredPrompt:
    return StructuredPrompt(system="Answer from sources.", user="How many rows?", strategy="g")


class ScriptedProvider(AbstractLLMProvider):
    """Plays a script of attempts: an exception fails, a string streams."""

    name = "scripted"
    model_name = "scripted-model"

    def __init__(self, *attempts: Exception | str, fail_after_first_chunk: bool = False) -> None:
        self._attempts = list(attempts)
        self._fail_after_first_chunk = fail_after_first_chunk
        self.attempts_made = 0

    async def generate(self, prompt: StructuredPrompt) -> LLMResult:  # pragma: no cover
        raise NotImplementedError("these tests are about stream()")

    async def stream(
        self, prompt: StructuredPrompt, stats: StreamStats,
    ) -> AsyncIterator[str]:
        self.attempts_made += 1
        step = self._attempts.pop(0) if self._attempts else ""
        if isinstance(step, Exception):
            raise step
        for piece in step.split("|"):
            yield piece
            if self._fail_after_first_chunk:
                raise LLMProviderError("deployment dropped mid-answer")
        stats.full_text = step.replace("|", "")


async def drain(engine: ReasoningEngine, prompt: StructuredPrompt) -> list[str]:
    stats = StreamStats()
    return [chunk async for chunk in engine.stream(prompt, stats)]


class TestRetryBeforeAnythingIsEmitted:
    async def test_a_transient_failure_is_retried_and_answers(self, prompt) -> None:
        """The exact failure that killed two real turns."""
        provider = ScriptedProvider(
            LLMProviderError("UnityWorks returned HTTP 500"), "There are |1252 rows."
        )
        chunks = await drain(ReasoningEngine(provider, max_retries=2), prompt)

        assert "".join(chunks) == "There are 1252 rows."
        assert provider.attempts_made == 2

    async def test_it_gives_up_after_the_configured_retries(self, prompt) -> None:
        provider = ScriptedProvider(*[LLMProviderError("HTTP 500")] * 3)
        with pytest.raises(ReasoningError):
            await drain(ReasoningEngine(provider, max_retries=2), prompt)
        assert provider.attempts_made == 3  # initial try + 2 retries

    async def test_zero_retries_means_one_attempt(self, prompt) -> None:
        provider = ScriptedProvider(LLMProviderError("HTTP 500"))
        with pytest.raises(ReasoningError):
            await drain(ReasoningEngine(provider, max_retries=0), prompt)
        assert provider.attempts_made == 1

    async def test_a_working_provider_is_not_retried(self, prompt) -> None:
        provider = ScriptedProvider("one|two")
        assert await drain(ReasoningEngine(provider, max_retries=2), prompt) == ["one", "two"]
        assert provider.attempts_made == 1

    async def test_the_final_error_names_the_provider_not_the_endpoint(self, prompt) -> None:
        provider = ScriptedProvider(*[LLMProviderError("HTTP 401 for key abc123")] * 3)
        with pytest.raises(ReasoningError) as caught:
            await drain(ReasoningEngine(provider, max_retries=2), prompt)
        assert "scripted" in str(caught.value)


class TestNoReplayOnceTheUserHasSeenSomething:
    async def test_a_mid_answer_failure_is_not_retried(self, prompt) -> None:
        """A replay here would print a second answer after half of a first one."""
        provider = ScriptedProvider("partial|rest", fail_after_first_chunk=True)
        with pytest.raises(ReasoningError):
            await drain(ReasoningEngine(provider, max_retries=2), prompt)
        assert provider.attempts_made == 1

    async def test_the_mid_answer_error_says_so(self, prompt) -> None:
        provider = ScriptedProvider("partial|rest", fail_after_first_chunk=True)
        with pytest.raises(ReasoningError, match="mid-answer"):
            await drain(ReasoningEngine(provider, max_retries=2), prompt)


class TestTheGatewayUsesIt:
    def test_the_streaming_turn_goes_through_the_engine(self) -> None:
        """The regression that mattered: the gateway called the raw provider.

        Read as source rather than exercised, because reaching this line needs a
        database, a conversation and a live endpoint - and the thing worth
        pinning is which object the call is made on.
        """
        import inspect

        from app.document_platform.conversation.gateway import ConversationGateway

        source = inspect.getsource(ConversationGateway.ask_stream)
        # The streaming turn no longer forwards provider tokens at all: it
        # generates, validates, persists, and only then emits what was saved,
        # because tokens sent before validation were read by the user and then
        # stored as NULL. What must not come back is the raw provider call,
        # which had no retries - a single transient 500 ended the turn.
        assert "self._answer_and_validate(" in source
        assert "self._reasoning.provider.stream(" not in source

    def test_the_answer_is_validated_before_any_of_it_is_shown(self) -> None:
        """Whatever reaches the screen is whatever reached the database."""
        import inspect

        from app.document_platform.conversation.gateway import ConversationGateway

        source = inspect.getsource(ConversationGateway.ask_stream)
        # Search forward from the generation step: ask_stream persists earlier
        # too, on the refusal short-circuit, and that occurrence is not the one
        # this is about.
        validated_at = source.index("_answer_and_validate")
        persisted_at = source.index("_persist(turn", validated_at)
        emitted_at = source.index('fmt("token"', validated_at)
        assert validated_at < persisted_at < emitted_at
