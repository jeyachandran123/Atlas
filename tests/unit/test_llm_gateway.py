"""The chat gateway: profiles, thinking, reasoning separation, retries, streaming.

Runs against a fake client shaped like ``AsyncOpenAI`` so no test ever reaches
NVIDIA, and every behaviour that matters in production is asserted here rather
than discovered there.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import openai
import pytest

from app.llm import gateway as gw
from app.llm.gateway import ChatGateway, LLMGatewayError
from app.llm.profiles import (
    AGENT_PLANNING, CODING, DOCUMENT, GENERAL, MATH, REASONING,
    list_profiles, profile_for_mode, resolve_profile, thinking_kwarg,
)

KEY = "nvapi-THIS-MUST-NEVER-APPEAR-IN-AN-ERROR"
NEMOTRON = "nvidia/nemotron-3-ultra-550b-a55b"


def settings(**over):
    base = dict(
        nvidia_api_key=KEY, vision_nvidia_api_key="", nvidia_base_url="https://x/v1",
        nvidia_chat_model=NEMOTRON, nvidia_reasoning_model=NEMOTRON, llm_profile_overrides="",
        llm_max_retries=2, llm_max_concurrency=4,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _status_error(cls, status):
    request = httpx.Request("POST", "https://x/v1/chat/completions")
    return cls(f"HTTP {status} {KEY}", response=httpx.Response(status, request=request), body=None)


def completion(content="answer", reasoning=None, finish="stop", prompt=10, out=20):
    extra = {"reasoning_content": reasoning} if reasoning is not None else {}
    message = SimpleNamespace(content=content, model_extra=extra)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=out),
    )


class FakeCompletions:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    async def create(self, **body):
        self.calls.append(body)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClient:
    def __init__(self, outcomes):
        self.chat = SimpleNamespace(completions=FakeCompletions(outcomes))

    def with_options(self, **_):
        return self

    @property
    def calls(self):
        return self.chat.completions.calls


def gateway(outcomes, **over):
    client = FakeClient(outcomes)
    g = ChatGateway(settings(**over), client=client)

    async def no_wait(*_):
        return None

    g._backoff = no_wait  # type: ignore[method-assign]
    return g, client


def switch(call):
    """The single thinking switch sent in a request, as (key, value)."""
    kwargs = call["extra_body"]["chat_template_kwargs"]
    assert len(kwargs) == 1
    return next(iter(kwargs.items()))


# ── profiles ─────────────────────────────────────────────────────────────────


class TestProfiles:
    def test_every_profile_uses_the_configured_chat_model(self):
        for p in list_profiles(settings(), public_only=False):
            assert p.model == NEMOTRON, p.name

    def test_reasoning_and_math_run_on_the_reasoning_model(self):
        s = settings(nvidia_chat_model="chat-m", nvidia_reasoning_model="deep-m")
        assert resolve_profile(REASONING, s).model == "deep-m"
        assert resolve_profile(MATH, s).model == "deep-m"
        for name in (GENERAL, CODING, AGENT_PLANNING, DOCUMENT):
            assert resolve_profile(name, s).model == "chat-m", name

    def test_no_reasoning_model_means_one_model_for_everything(self):
        s = settings(nvidia_chat_model="chat-m", nvidia_reasoning_model="")
        assert resolve_profile(REASONING, s).model == "chat-m"

    def test_an_override_beats_the_tier(self):
        s = settings(nvidia_chat_model="chat-m", nvidia_reasoning_model="deep-m",
                     llm_profile_overrides='{"coding": {"model": "deep-m"}}')
        assert resolve_profile(CODING, s).model == "deep-m"

    def test_thinking_defaults_match_what_each_job_needs(self):
        s = settings()
        assert resolve_profile(GENERAL, s).thinking is False
        assert resolve_profile(DOCUMENT, s).thinking is False
        for name in (REASONING, MATH, CODING, AGENT_PLANNING):
            assert resolve_profile(name, s).thinking is True, name

    def test_thinking_profiles_get_room_to_think(self):
        s = settings()
        assert resolve_profile(REASONING, s).max_tokens > resolve_profile(GENERAL, s).max_tokens

    def test_an_override_moves_one_profile_and_no_other(self):
        s = settings(llm_profile_overrides='{"coding": {"model": "qwen-coder", "thinking": false}}')
        coding = resolve_profile(CODING, s)
        assert coding.model == "qwen-coder" and coding.thinking is False
        assert resolve_profile(GENERAL, s).model == NEMOTRON

    def test_a_broken_override_is_ignored_not_fatal(self):
        s = settings(llm_profile_overrides="{not json")
        assert resolve_profile(CODING, s).model == NEMOTRON

    def test_an_override_cannot_set_unknown_fields(self):
        s = settings(llm_profile_overrides='{"general": {"api_key": "x", "temperature": 0.1}}')
        p = resolve_profile(GENERAL, s)
        assert p.temperature == 0.1 and not hasattr(p, "api_key")

    def test_an_unknown_profile_falls_back_to_general(self):
        assert resolve_profile("nonsense", settings()).name == GENERAL

    def test_chat_modes_map_onto_profiles(self):
        assert profile_for_mode("code") == CODING
        assert profile_for_mode("reasoning") == REASONING
        assert profile_for_mode("math") == MATH
        assert profile_for_mode("planning") == AGENT_PLANNING
        assert profile_for_mode("auto") == GENERAL
        assert profile_for_mode(None) == GENERAL
        assert profile_for_mode("something-new") == GENERAL


class TestThinkingSwitchName:
    """Model families name the switch differently, and the wrong name is
    silently ignored - so it is asserted, not assumed."""

    def test_nemotron_uses_enable_thinking(self):
        assert thinking_kwarg(NEMOTRON) == "enable_thinking"

    def test_deepseek_uses_thinking(self):
        assert thinking_kwarg("deepseek-ai/deepseek-v4-pro-0813") == "thinking"

    def test_an_explicit_control_wins_over_the_name(self):
        assert thinking_kwarg(NEMOTRON, "thinking") == "thinking"

    def test_none_sends_no_switch(self):
        assert thinking_kwarg(NEMOTRON, "none") is None


# ── one-shot ─────────────────────────────────────────────────────────────────


class TestComplete:
    async def test_thinking_follows_the_profile(self):
        g, client = gateway([completion(), completion()])
        await g.complete(user="hi", profile=GENERAL)
        await g.complete(user="hi", profile=REASONING)
        assert [switch(c) for c in client.calls] == [
            ("enable_thinking", False), ("enable_thinking", True),
        ]

    async def test_a_request_can_override_thinking_either_way(self):
        g, client = gateway([completion(), completion()])
        await g.complete(user="hi", profile=GENERAL, thinking=True)
        await g.complete(user="hi", profile=REASONING, thinking=False)
        assert [switch(c)[1] for c in client.calls] == [True, False]

    async def test_a_deepseek_model_gets_its_own_switch_name(self):
        g, client = gateway([completion()], nvidia_chat_model="deepseek-ai/deepseek-v4-pro-0813")
        await g.complete(user="hi", profile=CODING)  # chat tier, thinks by default
        assert switch(client.calls[0]) == ("thinking", True)

    async def test_a_model_without_a_switch_is_sent_none(self):
        g, client = gateway(
            [completion()], llm_profile_overrides='{"general": {"thinking_control": "none"}}',
        )
        await g.complete(user="hi", profile=GENERAL)
        assert "extra_body" not in client.calls[0]

    async def test_the_profile_decides_model_budget_and_temperature(self):
        g, client = gateway([completion()])
        await g.complete(user="hi", profile=MATH)
        body = client.calls[0]
        m = resolve_profile(MATH, settings())
        assert body["model"] == NEMOTRON
        assert body["max_tokens"] == m.max_tokens and body["temperature"] == m.temperature

    async def test_reasoning_comes_back_apart_from_the_answer(self):
        g, _ = gateway([completion(content="42", reasoning="6 times 7")])
        r = await g.complete(user="?", profile=MATH)
        assert r.text == "42" and r.reasoning == "6 times 7"

    async def test_inline_think_tags_are_split_out(self):
        g, _ = gateway([completion(content="<think>hmm</think>The answer.")])
        r = await g.complete(user="?")
        assert r.text == "The answer." and r.reasoning == "hmm"

    async def test_usage_is_reported(self):
        g, _ = gateway([completion(prompt=11, out=22)])
        r = await g.complete(user="?")
        assert (r.prompt_tokens, r.completion_tokens) == (11, 22)

    async def test_system_and_user_become_messages(self):
        g, client = gateway([completion()])
        await g.complete(user="q", system="be brief")
        assert client.calls[0]["messages"] == [
            {"role": "system", "content": "be brief"}, {"role": "user", "content": "q"},
        ]

    async def test_an_empty_prompt_is_refused_before_any_call(self):
        g, client = gateway([])
        with pytest.raises(LLMGatewayError):
            await g.complete(user="   ")
        assert client.calls == []

    async def test_a_budget_spent_entirely_on_thinking_is_an_error_not_a_blank(self):
        g, _ = gateway([completion(content="", reasoning="...", finish="length")])
        with pytest.raises(LLMGatewayError, match="output budget"):
            await g.complete(user="?", profile=REASONING)


class TestRetries:
    async def test_rate_limits_are_retried(self):
        g, client = gateway([_status_error(openai.RateLimitError, 429), completion("ok")])
        r = await g.complete(user="?")
        assert r.text == "ok" and r.attempts == 2 and len(client.calls) == 2

    async def test_a_rejected_key_is_not_retried(self):
        g, client = gateway([_status_error(openai.AuthenticationError, 401), completion()])
        with pytest.raises(LLMGatewayError) as e:
            await g.complete(user="?")
        assert len(client.calls) == 1 and e.value.status == 401

    async def test_retries_stop_at_the_limit(self):
        errors = [_status_error(openai.InternalServerError, 503) for _ in range(5)]
        g, client = gateway(errors, llm_max_retries=2)
        with pytest.raises(LLMGatewayError):
            await g.complete(user="?")
        assert len(client.calls) == 3

    async def test_errors_never_carry_the_key(self):
        g, _ = gateway([_status_error(openai.AuthenticationError, 401)])
        with pytest.raises(LLMGatewayError) as e:
            await g.complete(user="?")
        assert KEY not in str(e.value)

    async def test_no_key_is_a_clear_error(self):
        g = ChatGateway(settings(nvidia_api_key="", vision_nvidia_api_key=""))
        with pytest.raises(LLMGatewayError, match="NVIDIA_API_KEY"):
            await g.complete(user="?")


# ── streaming ────────────────────────────────────────────────────────────────


def _chunk(content=None, reasoning=None, finish=None, usage=None):
    extra = {"reasoning_content": reasoning} if reasoning else {}
    delta = SimpleNamespace(content=content, model_extra=extra)
    has_choice = content or reasoning or finish
    choices = [SimpleNamespace(delta=delta, finish_reason=finish)] if has_choice else []
    return SimpleNamespace(choices=choices, usage=usage)


class _Stream:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        item = self._chunks.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class TestStream:
    async def _collect(self, g, **kw):
        events = [e async for e in g.stream(user="?", **kw)]
        return (
            "".join(e.text for e in events if e.kind == "reasoning"),
            "".join(e.text for e in events if e.kind == "content"),
            events[-1],
        )

    async def test_reasoning_and_answer_arrive_as_separate_events(self):
        g, _ = gateway([_Stream([
            _chunk(reasoning="think "), _chunk(reasoning="more"),
            _chunk(content="The "), _chunk(content="answer", finish="stop"),
            _chunk(usage=SimpleNamespace(prompt_tokens=5, completion_tokens=9)),
        ])])
        thought, text, done = await self._collect(g, profile=REASONING)
        assert thought == "think more" and text == "The answer"
        assert done.kind == "done" and done.result.completion_tokens == 9

    async def test_inline_think_split_across_chunks_never_reaches_the_answer(self):
        g, _ = gateway([_Stream([
            _chunk(content="<think>step one"),
            _chunk(content=" step two</think>Hel"),
            _chunk(content="lo", finish="stop"),
        ])])
        thought, text, _ = await self._collect(g)
        assert thought == "step one step two" and text == "Hello"

    async def test_a_failure_before_any_output_is_retried(self):
        g, client = gateway([
            _status_error(openai.RateLimitError, 429),
            _Stream([_chunk(content="ok", finish="stop")]),
        ])
        _, text, _ = await self._collect(g)
        assert text == "ok" and len(client.calls) == 2

    async def test_a_failure_after_output_is_raised_not_repeated(self):
        g, client = gateway([_Stream([
            _chunk(content="partial"), _status_error(openai.InternalServerError, 503),
        ])])
        with pytest.raises(LLMGatewayError):
            await self._collect(g)
        assert len(client.calls) == 1

    async def test_streams_ask_for_usage(self):
        g, client = gateway([_Stream([_chunk(content="x", finish="stop")])])
        await self._collect(g)
        assert client.calls[0]["stream_options"] == {"include_usage": True}


def test_the_module_exports_one_process_wide_gateway(monkeypatch):
    monkeypatch.setattr(gw, "_gateway", None)
    assert gw.get_chat_gateway() is gw.get_chat_gateway()
    gw.reset_chat_gateway()
