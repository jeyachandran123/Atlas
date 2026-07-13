"""
Expansion Engine.

Plans targeted expansion of weak response sections.
Never regenerates the full response — only expands what is weak.

This reduces latency and token usage significantly.
The orchestrator uses the ExpansionPlan to append targeted content.
"""

from __future__ import annotations

from app.intelligence.reasoning.interfaces import AbstractExpansionEngine
from app.intelligence.reasoning.models import (
    ExpansionPlan,
    ExpansionTarget,
    ReflectionResult,
    ReflectionVerdict,
)

# Expansion instructions per section type
_EXPANSION_INSTRUCTIONS: dict[str, str] = {
    "code": (
        "Add a complete, working code implementation. "
        "Include imports, error handling, and inline comments."
    ),
    "example": (
        "Add 1-2 concrete, practical examples that illustrate the concept. "
        "Use realistic scenarios, not toy examples."
    ),
    "summary": (
        "Add a concise summary section that captures the 3-5 key takeaways. "
        "Use bullet points."
    ),
    "comparison": (
        "Add a structured comparison table with the key dimensions as columns "
        "and the options as rows."
    ),
    "steps": (
        "Restructure the relevant section as numbered steps. "
        "Each step should be actionable and self-contained."
    ),
    "explanation": (
        "Expand the explanation with more depth. "
        "Add the 'why' behind each point, not just the 'what'."
    ),
}


class ExpansionEngine(AbstractExpansionEngine):
    """
    Converts a ReflectionResult into a targeted ExpansionPlan.
    Only expands sections identified as weak — never the full response.
    """

    # Verdicts that require full regeneration instead of expansion
    _REGENERATE_VERDICTS = {ReflectionVerdict.MISSED_GOAL, ReflectionVerdict.STRATEGY_MISMATCH}

    def plan_expansion(
        self,
        response: str,
        reflection: ReflectionResult,
        context,
    ) -> ExpansionPlan:
        # Full regeneration needed for fundamental problems
        if reflection.verdict in self._REGENERATE_VERDICTS:
            return ExpansionPlan(
                targets=[],
                full_regeneration_needed=True,
                rationale=(
                    f"Full regeneration needed: {reflection.verdict.value}. "
                    f"{reflection.reflection_notes}"
                ),
            )

        # Satisfactory — no expansion needed
        if reflection.verdict == ReflectionVerdict.SATISFACTORY:
            return ExpansionPlan(
                targets=[],
                full_regeneration_needed=False,
                rationale="Response is satisfactory — no expansion needed",
            )

        # Build expansion targets from weak sections
        targets: list[ExpansionTarget] = []
        for priority, section in enumerate(reflection.weak_sections, start=1):
            instruction = _EXPANSION_INSTRUCTIONS.get(
                section.section_id,
                section.expansion_hint,
            )
            # Extract the relevant portion of the response for this section
            current_content = self._extract_section(response, section.section_id)

            targets.append(ExpansionTarget(
                section_id=section.section_id,
                current_content=current_content,
                expansion_instruction=instruction,
                priority=priority,
            ))

        return ExpansionPlan(
            targets=targets,
            full_regeneration_needed=False,
            rationale=(
                f"Expanding {len(targets)} weak section(s): "
                f"{', '.join(t.section_id for t in targets)}"
            ),
        )

    def _extract_section(self, response: str, section_id: str) -> str:
        """Extract the relevant portion of the response for a section."""
        # Simple heuristic: return last 200 chars as context for expansion
        if not response:
            return ""
        return response[-200:].strip()


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: ExpansionEngine | None = None


def get_expansion_engine() -> ExpansionEngine:
    global _engine
    if _engine is None:
        _engine = ExpansionEngine()
    return _engine
