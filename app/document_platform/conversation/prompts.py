"""
Prompt Builder (Objective 7) — structured context in, StructuredPrompt out.
Never retrieves anything. Strategies are pluggable; today there is one:
grounded answering with mandatory [S#] citations and an explicit refusal
protocol (the deterministic hook the Response Validator checks for).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.document_platform.conversation.context_builder import ContextBundle

# The exact sentence the model must open with when the sources cannot answer.
# Deterministic marker > vibes: the validator and gateway key off it.
REFUSAL_SENTENCE = "I don't have enough information in the knowledge base to answer that."

# Shown when an answer was produced but could not be verified against the
# sources. Distinct from REFUSAL_SENTENCE, which means the sources genuinely do
# not answer the question: this one means they might, and what came back could
# not be tied to them. Saying so is better than showing nothing, and far better
# than showing the unverified text.
UNVERIFIED_SENTENCE = (
    "I found an answer but could not tie it back to the sources, so I am not "
    "showing it. Try asking again, or more specifically."
)


# The citation rule, restated immediately before the model generates.
#
# It is already rule 1 of the system prompt, and that was not enough: measured
# against the deployed model with sources and question held fixed, rules at the
# top alone produced no citations, while the same rules restated after the
# question produced [S1], [S2]. Several thousand tokens of sources sit between
# the two positions, and instructions that far back stop being followed.
#
# The cost of losing this is not a missing footnote. The Response Validator
# rejects a factual answer with no [S#] marker, so an uncited answer reaches the
# user as "I don't have enough information in the knowledge base to answer
# that" — the sources having answered it perfectly well. Repeating the rule is
# how the answer survives validation; loosening the validator would instead let
# genuinely ungrounded answers through, which is the failure worth keeping.
CITATION_REMINDER = (
    "\n\nRemember: cite the source of every factual claim inline as [S1], [S2]. "
    "Cite only source numbers that appear above. An answer with no [S#] "
    "citation is rejected.\n"
    "This includes totals read from the 'document facts' source, which is "
    "numbered like any other: write \"there are 1252 rows [S5]\", never "
    "\"according to the document facts\". Naming a source in words instead of "
    "citing its number counts as not citing it, and the answer is thrown away."
)


@dataclass(frozen=True)
class HistoryTurn:
    question: str
    answer: str


# Measured against the deployed endpoint: it decodes at roughly 11 tokens a
# second, so the output budget is a latency budget. A grounded answer needs a
# few hundred tokens; the 8192 the platform allows a generation plan would be
# twelve minutes of decoding against a 300s timeout, and a long answer that
# outran the timeout reached the user as nothing at all.
ANSWER_MAX_TOKENS = 1024


@dataclass(frozen=True)
class StructuredPrompt:
    system: str
    user: str
    strategy: str
    max_output_tokens: int | None = None
    """Output ceiling for this prompt; None means the configured default.

    Callers differ by orders of magnitude - a conversation title wants tens of
    tokens, a generation plan wants thousands - and on a one-shot endpoint the
    ceiling is what decides how long the caller waits.
    """


class AbstractPromptStrategy(ABC):
    name: str = "abstract"

    @abstractmethod
    def build(
        self,
        question: str,
        bundle: ContextBundle,
        history: list[HistoryTurn],
    ) -> StructuredPrompt: ...


class GroundedAnswerStrategy(AbstractPromptStrategy):
    name = "grounded_answer"

    _SYSTEM = (
        "You are a precise enterprise knowledge assistant. Answer ONLY from the "
        "numbered sources provided. Rules:\n"
        "1. Every factual claim MUST cite its source inline as [S1], [S2], etc.\n"
        "2. Use ONLY the provided sources — never outside knowledge, never guesses.\n"
        f'3. If the sources do not contain the answer, reply EXACTLY: "{REFUSAL_SENTENCE}"\n'
        "4. Never invent citations. Only cite source numbers that exist.\n"
        "5. Be concise and direct. Answer in markdown.\n"
        "6. The numbered sources are excerpts, not the whole document. Never "
        "count them to answer 'how many' or 'how much' - a source block "
        "labelled 'document facts' carries the real totals. If the total you "
        "need is not there, say so instead of counting the excerpts."
    )

    def build(
        self,
        question: str,
        bundle: ContextBundle,
        history: list[HistoryTurn],
    ) -> StructuredPrompt:
        parts = ["# Sources\n"]
        for s in bundle.sources:
            header = f"[{s.source_id}]"
            if s.section_path:
                header += f" (section: {s.section_path})"
            parts.append(f"{header}\n{s.text}\n")
        if history:
            # Questions only. Previous *answers* are not context here, they
            # are a template: measured, with the last answer in the window
            # three different questions in one conversation all came back with
            # the same document summary, and trimming that answer to 400
            # characters only shortened the prefix the model continued from.
            #
            # What history is actually for is resolving "it" and "the other
            # one", and the questions carry that. The answers are regenerated
            # from freshly retrieved sources every turn anyway, which is the
            # whole point of a grounded pipeline - there is nothing in a past
            # answer that this turn's sources do not already contain.
            parts.append("# Earlier questions in this conversation, for context\n")
            for turn in history:
                parts.append(f"- {turn.question}")
            parts.append("")
        parts.append(f"# Question\n{question}")
        return StructuredPrompt(
            system=self._SYSTEM,
            user="\n".join(parts) + CITATION_REMINDER,
            strategy=self.name,
            max_output_tokens=ANSWER_MAX_TOKENS,
        )


class CitationRepairStrategy(AbstractPromptStrategy):
    """Ask for the same answer again, with its citations attached.

    The validator throws away a factual answer carrying no [S#] marker, and it
    is right to: an uncited claim cannot be checked against anything. But the
    common failure is not an ungrounded answer, it is a grounded one written
    carelessly - "according to the document facts, there are 1252 rows" is
    correct, sourced, and rejected on a formatting technicality.

    So the model is shown its own draft and asked to mark up where each claim
    came from. Nothing is loosened: the result goes through the same validator,
    and an answer that still cannot be tied to a source is still refused. What
    this removes is the case where the user is told the sources do not answer
    their question when the sources plainly did.
    """

    name = "citation_repair"

    _SYSTEM = (
        "You add source citations to an answer that already exists.\n"
        "1. Keep the wording. Do not rewrite, shorten, extend or re-order it.\n"
        "2. After each factual claim, add the [S#] of the source it came from.\n"
        "3. Use only source numbers listed below. Never invent one.\n"
        "4. If a claim matches no source, delete that claim.\n"
        "5. Reply with the cited answer only - no preamble, no explanation."
    )

    def build(
        self,
        question: str,
        bundle: ContextBundle,
        history: list[HistoryTurn],
        draft: str = "",
    ) -> StructuredPrompt:
        parts = ["# Sources\n"]
        for s in bundle.sources:
            header = f"[{s.source_id}]"
            if s.section_path:
                header += f" (section: {s.section_path})"
            parts.append(f"{header}\n{s.text}\n")
        parts.append(f"# Question\n{question}\n")
        parts.append(f"# Your answer, uncited\n{draft}\n")
        parts.append(
            "Return that answer with an [S#] after every factual claim. "
            "Available sources: " + ", ".join(f"[{s.source_id}]" for s in bundle.sources) + "."
        )
        return StructuredPrompt(
            system=self._SYSTEM,
            user="\n".join(parts),
            strategy=self.name,
            max_output_tokens=ANSWER_MAX_TOKENS,
        )


class PromptBuilder:
    def __init__(self) -> None:
        self._strategies: dict[str, AbstractPromptStrategy] = {
            "grounded_answer": GroundedAnswerStrategy(),
            "citation_repair": CitationRepairStrategy(),
        }

    def build(
        self,
        strategy: str,
        question: str,
        bundle: ContextBundle,
        history: list[HistoryTurn],
    ) -> StructuredPrompt:
        impl = self._strategies.get(strategy)
        if impl is None:
            raise ValueError(f"Unknown prompt strategy: {strategy}")
        return impl.build(question, bundle, history)

    def build_repair(
        self, question: str, bundle: ContextBundle, draft: str,
    ) -> StructuredPrompt:
        """The same answer, sent back for its citations."""
        return CitationRepairStrategy().build(question, bundle, [], draft)
