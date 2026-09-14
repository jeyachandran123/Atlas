"""On a one-shot endpoint the output budget is a latency budget.

Measured against the deployment, with prompt size and token budget varied one
at a time:

    26-char prompt,    512 tokens  ->  1.3 s
    26-char prompt,   8192 tokens  ->  1.2 s
    32k-char prompt,   512 tokens  ->  4.3 s
    32k-char prompt,  8192 tokens  ->  4.4 s

The budget costs nothing until it is used, and prompt size costs about three
seconds. What costs is decoding: a 1248-character answer took 27.5 s, roughly
11 tokens a second. So the ceiling decides the wait, and one 8192-token ceiling
was shared by everything - the answer, the workspace summary, the conversation
title, and the generation plan that actually needs it. A title of three words
was allowed twelve minutes of decoding against a 300 s timeout, and a long
answer that outran that timeout reached the user as nothing at all.

Each caller now states its own ceiling, and the configured value stays the
default for the generation planner that needs the room.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.document_platform.conversation.context_builder import ContextBundle, ContextSource
from app.document_platform.conversation.llm import UnityWorksLLMProvider, _unwrap_math
from app.document_platform.conversation.prompts import (
    ANSWER_MAX_TOKENS,
    GroundedAnswerStrategy,
    StructuredPrompt,
)

PREDICT_URL = "https://8001-dep-test.cloudspaces.litng.test/predict"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        unityworks_base_url=PREDICT_URL,
        unityworks_api_key="uw-test-key",  # noqa: S106 - fixture, not a credential
        unityworks_model="unityworks-vlm",
    )


class Recorder:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"output": "ok"})

    @property
    def last_budget(self) -> int:
        import json

        return json.loads(self.requests[-1].content.decode())["max_new_tokens"]


async def send(settings: Settings, prompt: StructuredPrompt) -> int:
    recorder = Recorder()
    provider = UnityWorksLLMProvider(settings, transport=recorder.transport())
    await provider.generate(prompt)
    return recorder.last_budget


class TestEachCallerStatesItsOwnCeiling:
    async def test_a_prompt_budget_is_sent(self, settings) -> None:
        budget = await send(
            settings, StructuredPrompt(system="s", user="u", strategy="t", max_output_tokens=32)
        )
        assert budget == 32

    async def test_no_prompt_budget_falls_back_to_configuration(self, settings) -> None:
        """The generation planner needs the configured room and keeps it."""
        budget = await send(settings, StructuredPrompt(system="s", user="u", strategy="plan"))
        assert budget == settings.dip_max_output_tokens

    async def test_the_default_still_fits_inside_the_request_timeout(self, settings) -> None:
        """A generation plan that cannot finish before the timeout produces nothing.

        The planner retries JSON drift twice and the engine retries transport
        twice underneath it, so a budget that always times out is not one slow
        request - it is six of them before the user is told anything.
        """
        worst_case_seconds = settings.dip_max_output_tokens / 11.0
        assert worst_case_seconds < settings.dip_llm_timeout_seconds

    async def test_the_default_is_still_room_for_a_real_plan(self, settings) -> None:
        assert settings.dip_max_output_tokens >= 2048


class TestTheAnswerStrategyCapsItself:
    def test_a_grounded_answer_asks_for_the_answer_ceiling(self) -> None:
        bundle = ContextBundle(
            sources=[
                ContextSource(
                    source_id="S1",
                    document_id="d",
                    knowledge_id="k",
                    chunk_ids=["c"],
                    seqs=[0],
                    section_path="Sheet1",
                    text="Id | Code",
                    confidence=0.7,
                    token_estimate=4,
                )
            ],
            total_tokens=4,
            best_confidence=0.7,
        )
        prompt = GroundedAnswerStrategy().build("What columns?", bundle, [])
        assert prompt.max_output_tokens == ANSWER_MAX_TOKENS

    def test_the_ceiling_fits_inside_the_request_timeout(self) -> None:
        """At the measured ~11 tokens/s a full answer must not outrun the timeout."""
        settings = Settings(_env_file=None)
        worst_case_seconds = ANSWER_MAX_TOKENS / 11.0
        assert worst_case_seconds < settings.dip_llm_timeout_seconds

    def test_the_ceiling_is_still_room_for_a_real_answer(self) -> None:
        assert ANSWER_MAX_TOKENS >= 512


class TestTheLatexEnvelopeComesOff:
    """The model closes numeric answers in display math; markdown renders none of it."""

    def test_a_restatement_of_a_number_already_given_is_dropped(self) -> None:
        assert (
            _unwrap_math(r"The number of rows is 1252. \[ \boxed{1252} \]")
            == "The number of rows is 1252."
        )

    def test_a_value_stated_only_in_the_box_is_kept(self) -> None:
        """Never remove a number the reader has not already been given."""
        assert _unwrap_math(r"Counting gives \[ \boxed{99} \]") == "Counting gives 99"

    def test_an_inline_box_is_unwrapped_in_place(self) -> None:
        assert _unwrap_math(r"Total \boxed{42} items") == "Total 42 items"

    def test_ordinary_prose_is_untouched(self) -> None:
        assert _unwrap_math("There are 1252 rows [S2].") == "There are 1252 rows [S2]."
