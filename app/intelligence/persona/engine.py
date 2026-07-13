"""
Persona Engine.

Selects the appropriate Atlas persona based on intent, complexity, and mode.
Personas are never hardcoded into prompts — they are selected here and
injected into the prompt composer as structured data.

Design:
- Each persona is a PersonaDefinition with a prompt fragment
- Persona selection is driven by a registry + selection rules
- Adding a new persona = registering one PersonaDefinition
"""

from __future__ import annotations

from dataclasses import dataclass

from app.intelligence.interfaces import AbstractPersonaEngine
from app.intelligence.models import (
    Complexity,
    ComplexityAnalysis,
    Intent,
    IntentAnalysis,
    Persona,
)


@dataclass
class PersonaDefinition:
    persona: Persona
    display_name: str
    prompt_fragment: str
    tone: str  # "formal" | "conversational" | "technical" | "educational"


# ── Persona Definitions ───────────────────────────────────────────────────────

_PERSONAS: dict[Persona, PersonaDefinition] = {
    Persona.TEACHER: PersonaDefinition(
        persona=Persona.TEACHER,
        display_name="Teacher",
        prompt_fragment=(
            "You are an expert teacher. Build understanding progressively. "
            "Start with fundamentals, use analogies, provide examples, and check comprehension. "
            "Never assume prior knowledge unless the user demonstrates it."
        ),
        tone="educational",
    ),
    Persona.SENIOR_ENGINEER: PersonaDefinition(
        persona=Persona.SENIOR_ENGINEER,
        display_name="Senior Software Engineer",
        prompt_fragment=(
            "You are a senior software engineer with 15+ years of experience. "
            "Write production-quality code. Consider edge cases, error handling, "
            "performance, and maintainability. Explain your design decisions."
        ),
        tone="technical",
    ),
    Persona.ARCHITECT: PersonaDefinition(
        persona=Persona.ARCHITECT,
        display_name="Software Architect",
        prompt_fragment=(
            "You are a software architect. Think in systems, not just code. "
            "Consider scalability, maintainability, team structure, and long-term evolution. "
            "Present trade-offs clearly. Use diagrams and structured breakdowns."
        ),
        tone="formal",
    ),
    Persona.RESEARCH_ASSISTANT: PersonaDefinition(
        persona=Persona.RESEARCH_ASSISTANT,
        display_name="Research Assistant",
        prompt_fragment=(
            "You are a research assistant. Synthesize information from multiple angles. "
            "Present findings objectively. Distinguish between established facts and emerging trends. "
            "Cite limitations of your knowledge where relevant."
        ),
        tone="formal",
    ),
    Persona.TECHNICAL_WRITER: PersonaDefinition(
        persona=Persona.TECHNICAL_WRITER,
        display_name="Technical Writer",
        prompt_fragment=(
            "You are a technical writer. Produce clear, structured, and accurate documentation. "
            "Use consistent terminology. Structure content with headers, examples, and summaries. "
            "Write for the target audience's level."
        ),
        tone="formal",
    ),
    Persona.REVIEWER: PersonaDefinition(
        persona=Persona.REVIEWER,
        display_name="Code Reviewer",
        prompt_fragment=(
            "You are an adversarial code reviewer. Your job is to find problems, not validate. "
            "Check for bugs, security issues, performance problems, and design flaws. "
            "Be specific and actionable. Prioritize issues by severity."
        ),
        tone="technical",
    ),
    Persona.DEBUGGER: PersonaDefinition(
        persona=Persona.DEBUGGER,
        display_name="Debugger",
        prompt_fragment=(
            "You are a systematic debugger. Diagnose root causes, not symptoms. "
            "Form hypotheses, eliminate possibilities, and explain your reasoning. "
            "Provide a fix and explain why it works."
        ),
        tone="technical",
    ),
}

# ── Selection Rules ───────────────────────────────────────────────────────────

# Intent → preferred persona
_INTENT_PERSONA_MAP: dict[Intent, Persona] = {
    Intent.CODING:              Persona.SENIOR_ENGINEER,
    Intent.DEBUGGING:           Persona.DEBUGGER,
    Intent.ARCHITECTURE:        Persona.ARCHITECT,
    Intent.LEARNING:            Persona.TEACHER,
    Intent.DEEP_TEACHING:       Persona.TEACHER,
    Intent.DOCUMENTATION:       Persona.TECHNICAL_WRITER,
    Intent.RESEARCH:            Persona.RESEARCH_ASSISTANT,
    Intent.BRAINSTORMING:       Persona.ARCHITECT,
    Intent.PLANNING:            Persona.ARCHITECT,
    Intent.REFACTORING:         Persona.SENIOR_ENGINEER,
    Intent.TESTING:             Persona.SENIOR_ENGINEER,
    Intent.RECOMMENDATION:      Persona.SENIOR_ENGINEER,
    Intent.COMPARISON:          Persona.RESEARCH_ASSISTANT,
    Intent.REPOSITORY_QUESTION: Persona.SENIOR_ENGINEER,
    Intent.GIT_OPERATIONS:      Persona.SENIOR_ENGINEER,
    Intent.TOOL_EXECUTION:      Persona.SENIOR_ENGINEER,
    Intent.GENERAL_CHAT:        Persona.TEACHER,
    Intent.UNKNOWN:             Persona.TEACHER,
    Intent.DOCUMENT_ANALYSIS:   Persona.RESEARCH_ASSISTANT,
}

# Agent mode overrides
_MODE_PERSONA_MAP: dict[str, Persona] = {
    "business": Persona.RESEARCH_ASSISTANT,
}


class PersonaEngine(AbstractPersonaEngine):
    """
    Selects the appropriate persona for a request.
    Mode overrides intent; intent overrides complexity defaults.
    """

    def select(
        self,
        intent_analysis: IntentAnalysis,
        agent_mode: str,
        complexity: ComplexityAnalysis,
    ) -> Persona:
        # Mode override takes highest priority
        if agent_mode in _MODE_PERSONA_MAP:
            return _MODE_PERSONA_MAP[agent_mode]

        # Intent-based selection
        persona = _INTENT_PERSONA_MAP.get(intent_analysis.primary.intent, Persona.TEACHER)

        # Upgrade to ARCHITECT for very complex requests
        if (
            complexity.level == Complexity.VERY_COMPLEX
            and persona == Persona.SENIOR_ENGINEER
        ):
            persona = Persona.ARCHITECT

        return persona

    def get_definition(self, persona: Persona) -> PersonaDefinition:
        return _PERSONAS[persona]


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: PersonaEngine | None = None


def get_persona_engine() -> PersonaEngine:
    global _engine
    if _engine is None:
        _engine = PersonaEngine()
    return _engine
