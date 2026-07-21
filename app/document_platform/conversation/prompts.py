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


@dataclass(frozen=True)
class HistoryTurn:
    question: str
    answer: str


@dataclass(frozen=True)
class StructuredPrompt:
    system: str
    user: str
    strategy: str


class AbstractPromptStrategy(ABC):
    name: str = "abstract"

    @abstractmethod
    def build(
        self, question: str, bundle: ContextBundle, history: list[HistoryTurn],
    ) -> StructuredPrompt: ...


class GroundedAnswerStrategy(AbstractPromptStrategy):
    name = "grounded_answer"

    _SYSTEM = (
        "You are a precise enterprise knowledge assistant. Answer ONLY from the "
        "numbered sources provided. Rules:\n"
        "1. Every factual claim MUST cite its source inline as [S1], [S2], etc.\n"
        "2. Use ONLY the provided sources — never outside knowledge, never guesses.\n"
        f"3. If the sources do not contain the answer, reply EXACTLY: \"{REFUSAL_SENTENCE}\"\n"
        "4. Never invent citations. Only cite source numbers that exist.\n"
        "5. Be concise and direct. Answer in markdown."
    )

    def build(
        self, question: str, bundle: ContextBundle, history: list[HistoryTurn],
    ) -> StructuredPrompt:
        parts = ["# Sources\n"]
        for s in bundle.sources:
            header = f"[{s.source_id}]"
            if s.section_path:
                header += f" (section: {s.section_path})"
            parts.append(f"{header}\n{s.text}\n")
        if history:
            parts.append("# Conversation so far\n")
            for turn in history:
                parts.append(f"User: {turn.question}\nAssistant: {turn.answer}\n")
        parts.append(f"# Question\n{question}")
        return StructuredPrompt(
            system=self._SYSTEM, user="\n".join(parts), strategy=self.name,
        )


class PromptBuilder:
    def __init__(self) -> None:
        self._strategies: dict[str, AbstractPromptStrategy] = {
            "grounded_answer": GroundedAnswerStrategy(),
        }

    def build(
        self, strategy: str, question: str, bundle: ContextBundle,
        history: list[HistoryTurn],
    ) -> StructuredPrompt:
        impl = self._strategies.get(strategy)
        if impl is None:
            raise ValueError(f"Unknown prompt strategy: {strategy}")
        return impl.build(question, bundle, history)
