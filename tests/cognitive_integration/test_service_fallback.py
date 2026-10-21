"""The brain service is fallback-safe: it never forces a broken answer into chat."""

from __future__ import annotations

import asyncio

from app.cognitive_integration.ports import TurnResult
from app.cognitive_integration.service import cognitive_turn


def _result(**kw) -> TurnResult:
    base = dict(reply="", authorized=False, decision="wait", escalated=False,
               conclusion=None, confidence=0.0, intent="general", stages={})
    base.update(kw)
    return TurnResult(**base)


class _Pipe:
    def __init__(self, result=None, raises=False):
        self._result = result
        self._raises = raises

    def handle(self, turn):
        if self._raises:
            raise RuntimeError("ollama down")
        return self._result


def _run(coro):
    """Run a coroutine on a private loop. asyncio.run() also unsets the current event
    loop on the way out, which breaks every async test that runs after this file."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_uses_brain_when_it_reaches_a_conclusion() -> None:
    pipe = _Pipe(_result(reply="Paris.", authorized=True, decision="approve", conclusion="Paris.", confidence=0.8))
    r = _run(cognitive_turn("capital of France?", pipeline=pipe))
    assert r is not None and r.reply == "Paris."


def test_uses_brain_when_it_escalates_a_dangerous_request() -> None:
    pipe = _Pipe(_result(reply="hold", decision="escalate", escalated=True, intent="danger"))
    r = _run(cognitive_turn("delete everything", pipeline=pipe))
    assert r is not None and r.escalated               # dangerous requests are NOT auto-answered


def test_falls_back_when_brain_has_no_conclusion() -> None:
    pipe = _Pipe(_result(reply="fallback", conclusion=None, escalated=False))
    assert _run(cognitive_turn("hi", pipeline=pipe)) is None   # -> caller uses the classic pipeline


def test_falls_back_when_brain_raises() -> None:
    assert _run(cognitive_turn("hi", pipeline=_Pipe(raises=True))) is None  # LLM down -> classic pipeline
