"""End-to-end integration: one conversational turn flows through the Cognitive OS.

Fakes are injected for the Ollama LLM, Intent Detector, Context Builder, and Generation
pipeline so the slice runs deterministically without any live service — proving the
*wiring*: Conversation -> Perception -> Working Memory -> Attention -> Reasoning ->
Reasoning Port -> (LLM) -> Executive -> Generation -> Response.
"""

from __future__ import annotations

from app.cognitive_integration import (
    CognitivePipeline,
    CognitiveSession,
    Turn,
    cognitive_brain_enabled,
)
from app.cognitive_integration.generation import GenerationAdapter
from app.cognitive_integration.perception import PerceptionAdapter
from app.cognitive_integration.platform_actions import PlatformActionAdapter
from app.cognitive_integration.ports import IntentResult

ENGINES = {"working_memory", "attention", "reasoning", "prediction",
           "executive", "metacognition", "learning", "development"}


# --- fakes (inject the Body without live services) ------------------------- #


class FakeLLM:
    """Stands in for the existing Ollama client behind the Reasoning Port."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete(self, prompt, *, system=None, model=None, temperature=0.15) -> str:
        self.calls.append(prompt)
        return "PARIS is the capital of France."


class FakeIntent:
    _DANGER = ("delete", "wipe", "destroy")

    def detect(self, message, history) -> IntentResult:
        danger = any(d in message.lower() for d in self._DANGER)
        return IntentResult(intent="danger" if danger else "general", is_question=True,
                            stakes=0.95 if danger else 0.1, safety_relevant=danger, irreversible=danger)


class FakeContext:
    def build(self, message, turn) -> str:
        return ""


class FakeGenerator:
    def render(self, conclusion, context_text, turn) -> str:
        return f"[reply] {conclusion}"


class FakePlatform:
    def execute(self, action, params):
        return {"hits": [f"result for {params.get('query')}"]}


def _build():
    llm = FakeLLM()
    session = CognitiveSession(llm)
    pipeline = CognitivePipeline(
        session, PerceptionAdapter(FakeIntent(), FakeContext()), GenerationAdapter(FakeGenerator()))
    return session, llm, pipeline


# --- wiring --------------------------------------------------------------- #


def test_session_boots_the_whole_brain_healthy() -> None:
    session, llm, _ = _build()
    try:
        assert ENGINES <= set(session.kernel.engine_registry().names())
        assert ENGINES <= set(session.runtime._orchestrator.names())          # noqa: SLF001
        assert session.services.health.overall().value == "healthy"
        # The Ollama-backed port IS the reasoning engine (no engine change).
        assert "generative_llm" in session.reasoning._pool.names()            # noqa: SLF001
    finally:
        session.shutdown()


# --- end-to-end flow ------------------------------------------------------ #


def test_normal_turn_flows_through_every_faculty() -> None:
    session, llm, pipeline = _build()
    try:
        result = pipeline.handle(Turn(message="What is the capital of France?"))
        # Perception -> Attention -> Reasoning(->LLM) -> Executive(approve) -> Generation.
        assert result.stages["attention_ignited"] is True
        assert result.stages["reasoning_concluded"] is True
        assert len(llm.calls) >= 1                          # reasoning invoked the Ollama port
        assert result.authorized and not result.escalated
        assert result.decision == "approve"
        assert "PARIS" in result.reply                      # the LLM answer, rendered by generation
    finally:
        session.shutdown()


def test_deliberate_governs_without_generating_for_streaming() -> None:
    session, llm, pipeline = _build()
    try:
        # Governance-only pass (used by the streaming path) does NOT call the LLM.
        normal = pipeline.deliberate(Turn(message="What is the capital of France?"))
        assert normal is not None and normal.authorized and not normal.escalated
        assert normal.system_prompt and normal.user_prompt      # prompts ready to stream
        assert len(llm.calls) == 0                              # answer is streamed later, not here

        danger = pipeline.deliberate(Turn(message="delete all my documents now"))
        assert danger is not None and danger.escalated and danger.hold_message  # safety gate, pre-generation
    finally:
        session.shutdown()


def test_dangerous_request_is_escalated_not_auto_answered() -> None:
    session, llm, pipeline = _build()
    try:
        result = pipeline.handle(Turn(message="delete all my documents now"))
        assert result.escalated and not result.authorized   # Executive safety gate (ExL13/P10)
        assert "review" in result.reply.lower() or "hold" in result.reply.lower()
        assert "PARIS" not in result.reply                  # not auto-answered / not acted upon
    finally:
        session.shutdown()


def test_state_and_ledger_integrity_after_turns() -> None:
    session, llm, pipeline = _build()
    try:
        pipeline.handle(Turn(message="Explain gravity."))
        pipeline.handle(Turn(message="And momentum?"))
        assert session.services.ledger.verify()
        assert session.state.verify_integrity()
        # Prediction / Meta / Development remain read-only even under the live flow.
        assert session.prediction.canonical_writes() == 0
    finally:
        session.shutdown()


# --- platform action adapter (the seam for future organs) ----------------- #


def test_platform_action_adapter_dispatches_to_an_injected_organ() -> None:
    adapter = PlatformActionAdapter({"document": FakePlatform()})
    out = adapter.dispatch("search_document", {"query": "invoices"}, None)
    assert out["executed"] and out["organ"] == "document" and out["result"]["hits"]
    # An unwired organ is reported, never crashes.
    assert adapter.dispatch("search_knowledge", {"query": "x"}, None)["executed"] is False


# --- feature flag --------------------------------------------------------- #


def test_feature_flag_off_when_disabled(monkeypatch) -> None:
    class _S:
        cognitive_brain_enabled = False

    monkeypatch.setattr("app.config.get_settings", lambda: _S())
    assert cognitive_brain_enabled() is False               # disabled -> existing pipeline unchanged


def test_feature_flag_on_when_enabled(monkeypatch) -> None:
    class _S:
        cognitive_brain_enabled = True

    monkeypatch.setattr("app.config.get_settings", lambda: _S())
    assert cognitive_brain_enabled() is True                # enabled -> Conversation routes through the brain
