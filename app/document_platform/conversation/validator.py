"""
Response Validator (Objective 11) — the trust gate. An answer only reaches
the user if every citation marker resolves, grounding meets the threshold,
and factual answers actually cite something. Refusals (the model's honest
"the sources don't say") are VALID outcomes — grounded=false, not errors.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.document_platform.conversation.citations import CitationOutcome
from app.document_platform.conversation.context_builder import ContextBundle
from app.document_platform.conversation.prompts import REFUSAL_SENTENCE


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    grounded: bool                   # a factual, cited answer (False for refusals)
    grounding_score: float
    is_refusal: bool = False
    reasons: list[str] = field(default_factory=list)


class ResponseValidator:
    def __init__(self, min_grounding_score: float) -> None:
        self._min_score = min_grounding_score

    def validate(
        self, answer: str, outcome: CitationOutcome, bundle: ContextBundle,
    ) -> ValidationResult:
        text = answer.strip()
        if not text:
            return ValidationResult(
                valid=False, grounded=False, grounding_score=0.0,
                reasons=["empty_response"],
            )

        # The model's honest refusal is the *designed* no-knowledge path.
        if REFUSAL_SENTENCE.rstrip(".").lower() in text.lower():
            return ValidationResult(
                valid=True, grounded=False, grounding_score=0.0, is_refusal=True,
                reasons=["model_refusal_no_source"],
            )

        reasons: list[str] = []
        if outcome.unresolved_markers:
            reasons.append(f"invented_citations:{','.join(outcome.unresolved_markers)}")
        if not outcome.citations:
            reasons.append("missing_citations")
        grounding_score = (
            round(sum(c.confidence for c in outcome.citations) / len(outcome.citations), 4)
            if outcome.citations else 0.0
        )
        if outcome.citations and grounding_score < self._min_score:
            reasons.append(f"grounding_below_threshold:{grounding_score}<{self._min_score}")

        if reasons:
            return ValidationResult(
                valid=False, grounded=False, grounding_score=grounding_score, reasons=reasons,
            )
        return ValidationResult(valid=True, grounded=True, grounding_score=grounding_score)
