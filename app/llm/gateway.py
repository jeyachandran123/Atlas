"""The one door to the chat model.

Every text-generating call in the application comes through here: the coding
assistant, the document workspace, the Cognitive Kernel, code generation for
document tasks. Vision stays on its own adapters - it has a different port, a
different payload and a different model - and embeddings stay local.

What lives here and nowhere else:

* **The client.** One ``AsyncOpenAI`` for the process, so connections are pooled
  and TLS is negotiated once instead of on every request.
* **Retries.** Rate limits, timeouts, dropped connections and 5xx are retried
  with backoff; 4xx are not, because asking again will not change the answer.
* **Concurrency.** A semaphore caps calls in flight. The hosted tier rate-limits
  per minute, and fifty users pressing Send together should queue briefly here
  rather than all fail with 429 at once.
* **Thinking.** Turned on or off per profile, overridable per request, and the
  reasoning is returned *separately* from the answer - never mixed into text
  that a validator or a user will read as the reply.
* **Honest errors.** A failure says what failed and never includes the key.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterable, Literal

from loguru import logger

from app.llm.profiles import ChatProfile, resolve_profile, thinking_kwarg

Message = dict[str, str]

_THINK_BLOCK = re.compile(r"<think>.*?</think>\s*", re.DOTALL | re.IGNORECASE)
_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"

_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class LLMGatewayError(Exception):
    """The model could not produce an answer. The message is safe to show."""

    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@dataclass(frozen=True)
class ChatResult:
    text: str
    reasoning: str
    model: str
    profile: str
    thinking: bool
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    finish_reason: str = ""
    attempts: int = 1

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"

    @property
    def tokens_per_second(self) -> float:
        return self.completion_tokens / (self.latency_ms / 1000) if self.latency_ms else 0.0


@dataclass
class StreamEvent:
    kind: Literal["reasoning", "content", "done"]
    text: str = ""
    result: ChatResult | None = None


@dataclass
class _Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = ""
    reasoning: list[str] = field(default_factory=list)
    content: list[str] = field(default_factory=list)


def _messages(
    messages: Iterable[Message] | None, user: str | None, system: str | None,
) -> list[Message]:
    if messages is not None:
        out = [dict(m) for m in messages]
    else:
        out = []
        if system:
            out.append({"role": "system", "content": system})
        out.append({"role": "user", "content": user or ""})
    if not out or not any((m.get("content") or "").strip() for m in out):
        raise LLMGatewayError("Nothing to send to the model: the prompt is empty.")
    return out


def _split_reasoning(content: str, reasoning: str) -> tuple[str, str]:
    """Separate the answer from any thinking that leaked into it.

    Models that honour the thinking switch put their reasoning in a separate
    ``reasoning_content`` field. Some put it inline as ``<think>…</think>``
    instead. Either way the caller gets the answer and the reasoning apart,
    because a validator that sees the thinking treats it as the answer.
    """
    inline = _THINK_BLOCK.findall(content)
    if inline:
        extra = "".join(block[len(_THINK_OPEN):].rsplit(_THINK_CLOSE, 1)[0] for block in inline)
        reasoning = (reasoning + "\n" + extra).strip() if reasoning else extra.strip()
        content = _THINK_BLOCK.sub("", content)
    elif _THINK_OPEN in content and _THINK_CLOSE not in content:
        # Truncated mid-thought: everything after <think> is reasoning.
        before, after = content.split(_THINK_OPEN, 1)
        reasoning = (reasoning + "\n" + after).strip() if reasoning else after.strip()
        content = before
    return content.strip(), reasoning.strip()


def _field(obj: Any, name: str) -> Any:
    value = getattr(obj, name, None)
    if value is None:
        extra = getattr(obj, "model_extra", None) or {}
        value = extra.get(name)
    return value


class ChatGateway:
    def __init__(self, settings: Any = None, *, client: Any = None) -> None:
        if settings is None:
            from app.config import get_settings

            settings = get_settings()
        self._settings = settings
        self._client = client
        self._max_retries = max(0, int(getattr(settings, "llm_max_retries", 2)))
        self._semaphore = asyncio.Semaphore(
            max(1, int(getattr(settings, "llm_max_concurrency", 8)))
        )

    # ── client ────────────────────────────────────────────────────────────────

    def _api_key(self) -> str:
        for name in ("nvidia_api_key", "vision_nvidia_api_key"):
            value = getattr(self._settings, name, "")
            if hasattr(value, "get_secret_value"):
                value = value.get_secret_value()
            if value:
                return str(value)
        return ""

    def _get_client(self) -> Any:
        if self._client is None:
            key = self._api_key()
            if not key:
                raise LLMGatewayError(
                    "No NVIDIA API key is configured (NVIDIA_API_KEY), so there is "
                    "no chat model to answer with."
                )
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                base_url=str(getattr(self._settings, "nvidia_base_url", "")
                             or "https://integrate.api.nvidia.com/v1"),
                api_key=key,
                max_retries=0,  # retries are ours, so they are counted and logged
            )
        return self._client

    def profile(self, name: str | None) -> ChatProfile:
        return resolve_profile(name, self._settings)

    # ── request shaping ───────────────────────────────────────────────────────

    def _request(
        self, profile: ChatProfile, messages: list[Message], *, thinking: bool,
        temperature: float | None, max_tokens: int | None, stop: list[str] | None,
        stream: bool, seed: int | None,
    ) -> dict[str, Any]:
        if not profile.model:
            raise LLMGatewayError(
                "No chat model is configured (NVIDIA_CHAT_MODEL is empty)."
            )
        body: dict[str, Any] = {
            "model": profile.model,
            "messages": messages,
            "temperature": profile.temperature if temperature is None else temperature,
            "top_p": profile.top_p,
            "max_tokens": max_tokens or profile.max_tokens,
            "stream": stream,
        }
        if stop:
            body["stop"] = stop
        if seed is not None:
            body["seed"] = seed
        if stream:
            body["stream_options"] = {"include_usage": True}
        switch = thinking_kwarg(profile.model, profile.thinking_control)
        if switch:
            body["extra_body"] = {"chat_template_kwargs": {switch: bool(thinking)}}
        return body

    @staticmethod
    def _classify(exc: Exception) -> LLMGatewayError:
        """Turn a client exception into one safe to log and show.

        Only the class and the status survive. Provider error bodies can echo
        the request back, and the request carries the key in its headers.
        """
        import openai

        if isinstance(exc, LLMGatewayError):
            return exc
        if isinstance(exc, openai.APITimeoutError):
            return LLMGatewayError("The chat model did not answer in time.", retryable=True)
        if isinstance(exc, openai.APIConnectionError):
            return LLMGatewayError("Could not reach the chat model.", retryable=True)
        if isinstance(exc, openai.APIStatusError):
            status = exc.status_code
            reason = {
                401: "The NVIDIA API key was rejected.",
                403: "The NVIDIA API key is not allowed to use this model.",
                404: "The configured chat model does not exist on this endpoint.",
                429: "The chat model is rate-limited right now.",
            }.get(status, f"The chat model returned HTTP {status}.")
            return LLMGatewayError(reason, retryable=status in _RETRYABLE_STATUS, status=status)
        return LLMGatewayError(f"The chat call failed ({type(exc).__name__}).", retryable=False)

    async def _backoff(self, attempt: int, error: LLMGatewayError) -> None:
        base = 2.0 if error.status == 429 else 0.8
        delay = min(20.0, base * (2 ** (attempt - 1))) * (0.7 + random.random() * 0.6)
        logger.warning(f"Chat model: {error} Retrying in {delay:.1f}s (attempt {attempt + 1})")
        await asyncio.sleep(delay)

    # ── one-shot ──────────────────────────────────────────────────────────────

    async def complete(
        self,
        messages: Iterable[Message] | None = None,
        *,
        user: str | None = None,
        system: str | None = None,
        profile: str | None = None,
        thinking: bool | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        seed: int | None = None,
    ) -> ChatResult:
        spec = self.profile(profile)
        use_thinking = spec.thinking if thinking is None else bool(thinking)
        convo = _messages(messages, user, system)
        body = self._request(
            spec, convo, thinking=use_thinking, temperature=temperature,
            max_tokens=max_tokens, stop=stop, stream=False, seed=seed,
        )
        client = self._get_client().with_options(timeout=spec.timeout_seconds)

        attempt = 0
        start = time.monotonic()
        while True:
            attempt += 1
            try:
                async with self._semaphore:
                    completion = await client.chat.completions.create(**body)
                break
            except Exception as exc:  # noqa: BLE001 - classified below
                error = self._classify(exc)
                if not error.retryable or attempt > self._max_retries:
                    logger.error(f"Chat model [{spec.name}/{spec.model}] failed: {error}")
                    raise error from exc
                await self._backoff(attempt, error)

        latency_ms = int((time.monotonic() - start) * 1000)
        choice = completion.choices[0] if completion.choices else None
        message = choice.message if choice else None
        content = (getattr(message, "content", None) or "") if message else ""
        reasoning = (_field(message, "reasoning_content") or "") if message else ""
        text, reasoning = _split_reasoning(str(content), str(reasoning))
        usage = getattr(completion, "usage", None)
        result = ChatResult(
            text=text,
            reasoning=reasoning,
            model=spec.model,
            profile=spec.name,
            thinking=use_thinking,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            latency_ms=latency_ms,
            finish_reason=str(getattr(choice, "finish_reason", "") or ""),
            attempts=attempt,
        )
        self._log(result)
        if not result.text and result.truncated:
            # A thinking model that spent its whole budget thinking. Reported,
            # not hidden: an empty "success" is how a blank reply reaches a user.
            raise LLMGatewayError(
                "The model used its whole output budget before answering. "
                "Raise max_tokens for this profile or turn thinking off.",
                retryable=False,
            )
        return result

    # ── streaming ─────────────────────────────────────────────────────────────

    async def stream(
        self,
        messages: Iterable[Message] | None = None,
        *,
        user: str | None = None,
        system: str | None = None,
        profile: str | None = None,
        thinking: bool | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        seed: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Reasoning and answer as they are produced, then one ``done`` event.

        Retried only until the first event arrives. After that a retry would
        repeat text the user has already read, so a mid-stream failure is
        raised instead and the caller decides what to show.
        """
        spec = self.profile(profile)
        use_thinking = spec.thinking if thinking is None else bool(thinking)
        convo = _messages(messages, user, system)
        body = self._request(
            spec, convo, thinking=use_thinking, temperature=temperature,
            max_tokens=max_tokens, stop=stop, stream=True, seed=seed,
        )
        client = self._get_client().with_options(timeout=spec.timeout_seconds)

        usage = _Usage()
        start = time.monotonic()
        attempt = 0
        emitted = False
        in_think = False

        async with self._semaphore:
            while True:
                attempt += 1
                try:
                    response = await client.chat.completions.create(**body)
                    async for chunk in response:
                        if getattr(chunk, "usage", None):
                            usage.prompt_tokens = int(chunk.usage.prompt_tokens or 0)
                            usage.completion_tokens = int(chunk.usage.completion_tokens or 0)
                        if not chunk.choices:
                            continue
                        choice = chunk.choices[0]
                        if choice.finish_reason:
                            usage.finish_reason = str(choice.finish_reason)
                        delta = choice.delta
                        thought = _field(delta, "reasoning_content")
                        if thought:
                            usage.reasoning.append(thought)
                            emitted = True
                            yield StreamEvent("reasoning", thought)
                        piece = getattr(delta, "content", None)
                        if not piece:
                            continue
                        # Inline <think> blocks, split across chunks.
                        while piece:
                            if in_think:
                                if _THINK_CLOSE in piece:
                                    thought, piece = piece.split(_THINK_CLOSE, 1)
                                    in_think = False
                                else:
                                    thought, piece = piece, ""
                                if thought:
                                    usage.reasoning.append(thought)
                                    emitted = True
                                    yield StreamEvent("reasoning", thought)
                            elif _THINK_OPEN in piece:
                                before, piece = piece.split(_THINK_OPEN, 1)
                                in_think = True
                                if before:
                                    usage.content.append(before)
                                    emitted = True
                                    yield StreamEvent("content", before)
                            else:
                                usage.content.append(piece)
                                emitted = True
                                yield StreamEvent("content", piece)
                                piece = ""
                    break
                except Exception as exc:  # noqa: BLE001 - classified below
                    error = self._classify(exc)
                    if emitted or not error.retryable or attempt > self._max_retries:
                        logger.error(f"Chat stream [{spec.name}/{spec.model}] failed: {error}")
                        raise error from exc
                    await self._backoff(attempt, error)

        result = ChatResult(
            text="".join(usage.content).strip(),
            reasoning="".join(usage.reasoning).strip(),
            model=spec.model,
            profile=spec.name,
            thinking=use_thinking,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            latency_ms=int((time.monotonic() - start) * 1000),
            finish_reason=usage.finish_reason,
            attempts=attempt,
        )
        self._log(result)
        yield StreamEvent("done", result=result)

    # ── convenience ───────────────────────────────────────────────────────────

    async def text(self, user: str, *, system: str | None = None, **kwargs: Any) -> str:
        return (await self.complete(user=user, system=system, **kwargs)).text

    @staticmethod
    def _log(result: ChatResult) -> None:
        logger.info(
            f"Chat model [{result.profile}/{result.model}] thinking={result.thinking} "
            f"{result.completion_tokens} tok in {result.latency_ms}ms "
            f"({result.tokens_per_second:.0f} tok/s) finish={result.finish_reason or '-'}"
            + (f" attempts={result.attempts}" if result.attempts > 1 else "")
        )


_gateway: ChatGateway | None = None


def get_chat_gateway() -> ChatGateway:
    """The process-wide gateway, built on first use."""
    global _gateway
    if _gateway is None:
        _gateway = ChatGateway()
    return _gateway


def reset_chat_gateway() -> None:
    """Drop the cached gateway. For tests and configuration reloads."""
    global _gateway
    _gateway = None
