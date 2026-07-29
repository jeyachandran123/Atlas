"""Generation Adapter — a cognitive conclusion becomes a natural-language reply.

    Reasoning conclusion -> Generation Platform -> reply -> Conversation -> User

Reuses the *existing* Generation pipeline (via the ``GenerationPort``). It renders the
Executive-authorized conclusion into the final conversational response. It never
reasons or decides — it only renders. A safe fallback is returned if generation yields
nothing.
"""

from __future__ import annotations

from .ports import GenerationPort, Turn

_FALLBACK = "I wasn't able to produce a confident answer to that just now."


class GenerationAdapter:
    def __init__(self, generator: GenerationPort) -> None:
        self._generator = generator

    def render(self, conclusion: str | None, context_text: str, turn: Turn) -> str:
        if not conclusion:
            return _FALLBACK
        try:
            reply = self._generator.render(conclusion, context_text, turn)
        except Exception:
            return conclusion  # degrade to the raw conclusion rather than failing the turn
        return (reply or "").strip() or conclusion
