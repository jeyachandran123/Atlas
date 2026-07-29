"""Perception Adapter — Conversation input becomes cognitive objects.

    Conversation -> Intent Detector -> Context Builder -> Cognitive Objects

Reuses the *existing* Intent Detector and Context Builder (via ports). It renders the
message into a goal (R2), a percept (R5), and context evidence (R5), and makes them
conscious by loading them into Working Memory through WM's public runtime API. It
never reasons — it only perceives. Intent risk (stakes / safety / reversibility) is
carried forward so the Executive can gate authorization.
"""

from __future__ import annotations

from typing import Any

from app.cognitive_kernel.state import ObjectType

from .ports import ContextPort, IntentPort, PerceivedInput, Turn


class PerceptionAdapter:
    def __init__(self, intent: IntentPort, context: ContextPort) -> None:
        self._intent = intent
        self._context = context

    def perceive(self, session: Any, turn: Turn, ctx: Any) -> PerceivedInput:
        intent = self._intent.detect(turn.message, list(turn.history))
        context_text = self._context.build(turn.message, turn)

        tx = session.state.begin_transaction(ctx)
        goal_handle = tx.create(
            ObjectType.GOAL,
            payload={"title": turn.message[:120], "state": "active", "owner": turn.user_id,
                     "tier": "tactical", "statement": turn.message, "intent": intent.intent},
            salience=0.9, provenance=f"conversation:{turn.conversation_id}",
        )
        # The percept anchors the message in consciousness, but its statement is a distinct
        # label (not the query itself) so the query is not treated as self-corroborating
        # evidence — the reasoning conclusion must come from the reasoning engine, not the echo.
        percept_handle = tx.create(
            ObjectType.PERCEPT,
            payload={"statement": f"user_message: {turn.message[:400]}", "text": turn.message, "source": "user"},
            confidence=0.95)
        evidence = [percept_handle]
        if context_text:
            ctx_handle = tx.create(
                ObjectType.EVIDENCE, payload={"statement": context_text[:500], "source": "context"},
                confidence=0.8)
            evidence.append(ctx_handle)
        tx.commit()

        # Make the perceived content conscious (Working Memory, via its public runtime API).
        for handle in evidence:
            session.wm_api.load(handle, ctx)

        return PerceivedInput(
            goal=turn.message, question=turn.message, intent=intent.intent, stakes=intent.stakes,
            safety_relevant=intent.safety_relevant,
            reversibility=0.0 if intent.irreversible else 1.0,
            goal_handle=goal_handle, evidence_handles=tuple(evidence), context_text=context_text,
        )
