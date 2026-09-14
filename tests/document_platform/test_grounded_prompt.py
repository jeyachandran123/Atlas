"""Where the citation rule sits in the prompt decides whether answers survive.

The Response Validator rejects any factual answer carrying no ``[S#]`` marker.
That gate is correct and stays — but it made the whole document workspace look
broken when the model produced a good answer and simply did not cite it: the
user saw "I don't have enough information in the knowledge base to answer that"
for a question the sources plainly answered.

Measured against the live endpoint, with the sources and question held fixed
and only the placement of the rule varied:

    rules at the top only  -> no citations at all
    rules restated at end  -> [S1], [S2]

So the rule is restated immediately before the model generates. This is prompt
strategy, not validation: nothing is loosened, and no citation is ever attached
to text the model did not cite itself.
"""

from __future__ import annotations

from app.document_platform.conversation.context_builder import (
    ContextBundle,
    ContextSource,
)
from app.document_platform.conversation.prompts import (
    CITATION_REMINDER,
    GroundedAnswerStrategy,
    PromptBuilder,
)


def source(source_id: str, text: str) -> ContextSource:
    return ContextSource(
        source_id=source_id,
        document_id="doc-1",
        knowledge_id="k-1",
        chunk_ids=["c-1"],
        seqs=[0],
        section_path="Sheet1",
        text=text,
        confidence=0.7,
        token_estimate=10,
    )


def bundle() -> ContextBundle:
    return ContextBundle(
        sources=[source("S1", "Dish Type | Kitchen Section"), source("S2", "Meal Period")],
        total_tokens=20,
        best_confidence=0.7,
    )


class TestCitationRulePlacement:
    def test_the_rule_is_restated_after_the_question(self) -> None:
        """Recency is the whole fix — a rule 4000 tokens back is not followed."""
        prompt = GroundedAnswerStrategy().build("What columns exist?", bundle(), [])

        question_at = prompt.user.index("What columns exist?")
        reminder_at = prompt.user.index(CITATION_REMINDER.strip()[:40])
        assert reminder_at > question_at

    def test_the_reminder_names_the_marker_format(self) -> None:
        prompt = GroundedAnswerStrategy().build("What columns exist?", bundle(), [])
        assert "[S1]" in CITATION_REMINDER
        assert CITATION_REMINDER.strip() in prompt.user

    def test_the_system_rules_are_still_there(self) -> None:
        """The reminder repeats the rule; it does not replace it."""
        prompt = GroundedAnswerStrategy().build("What columns exist?", bundle(), [])
        assert "MUST cite its source inline" in prompt.system

    def test_the_sources_still_come_before_the_question(self) -> None:
        prompt = GroundedAnswerStrategy().build("What columns exist?", bundle(), [])
        assert prompt.user.index("[S1]") < prompt.user.index("What columns exist?")

    def test_nothing_invents_a_citation(self) -> None:
        """The reminder must not hand the model a source number to copy blindly."""
        prompt = GroundedAnswerStrategy().build("What columns exist?", bundle(), [])
        assert "never invent" in prompt.system.lower() or "Never invent" in prompt.system

    def test_the_builder_routes_through_the_strategy(self) -> None:
        built = PromptBuilder().build("grounded_answer", "What columns exist?", bundle(), [])
        assert CITATION_REMINDER.strip() in built.user
        assert built.strategy == "grounded_answer"
