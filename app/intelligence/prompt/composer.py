"""
Dynamic Prompt Composer — V2.

Builds the system prompt from a PromptPlan produced by the PromptIntelligenceEngine.
No static templates. Every section is derived from analysis.

Sections assembled (only those that add value are included):
  1. Identity
  2. Personality principles (behavioural, not scripted)
  3. Response strategy instruction
  4. Depth instruction
  5. Conversation continuity note
  6. Policy warnings
  7. Domain knowledge modules (from registry, only when relevant)
  8. Long-term memory
  9. Code context
  10. Tool results
"""

from __future__ import annotations

from app.intelligence.interfaces import AbstractPromptComposer
from app.intelligence.models import (
    IntelligenceContext,
    Intent,
    Persona,
    PolicyDecision,
    ResponseStrategy,
)
from app.intelligence.persona.engine import _PERSONAS
from app.intelligence.prompting.engine import PromptIntelligenceEngine, get_prompt_intelligence_engine
from app.intelligence.strategy.planner import STRATEGY_REGISTRY


def _get_domain_registry() -> dict:
    from app.prompts.registry import REGISTRY
    return REGISTRY


# ── Section builders ──────────────────────────────────────────────────────────

def _build_identity() -> str:
    return (
        "You are Atlas, an AI engineering platform. "
        "You are a specialized engineering intelligence built to help software teams "
        "design, build, debug, and understand software systems. "
        "You also answer general knowledge, science, and educational questions with depth and clarity."
    )


def _build_personality_section(principles: list[str]) -> str:
    if not principles:
        return ""
    return "Behavioural principles:\n" + "\n".join(f"- {p}" for p in principles)


def _build_strategy_section(strategy: ResponseStrategy) -> str:
    definition = STRATEGY_REGISTRY.get(strategy)
    if not definition:
        return ""
    return definition.prompt_fragment


def _build_policy_section(context: IntelligenceContext) -> str:
    if context.policy.decision == PolicyDecision.WARN:
        return (
            f"Note: {context.policy.reason}. "
            "Proceed with appropriate caution and disclaimers."
        )
    return ""


def _build_continuity_section(continuity_note: str) -> str:
    return continuity_note  # already a clean sentence from context resolver


def _build_memory_section(context: IntelligenceContext) -> str:
    if not context.memory_context:
        return ""
    return f"Long-term context about this user:\n{context.memory_context}"


def _build_code_context_section(context: IntelligenceContext) -> str:
    if not context.code_context_block:
        return ""
    return (
        f"Retrieved code context ({context.retrieved_chunks_count} chunks):\n"
        f"{context.code_context_block}"
    )


def _build_tool_results_section(context: IntelligenceContext) -> str:
    if not context.tool_results:
        return ""
    lines = []
    for result in context.tool_results:
        status = "✓" if getattr(result, "success", True) else "✗"
        output = str(getattr(result, "output", result) or "")[:500]
        tool_name = getattr(result, "tool_name", "tool")
        lines.append(f"[{status}] {tool_name}: {output}")
    return "Tool results:\n" + "\n".join(lines)


def _select_domain_modules(context: IntelligenceContext) -> list[str]:
    """Select domain modules only when genuinely relevant."""
    registry = _get_domain_registry()
    message = context.user_message.lower()
    selected: list[str] = []
    seen: set[str] = set()

    def add(key: str) -> None:
        if key not in seen and key in registry:
            seen.add(key)
            selected.append(key)

    lang_map = {
        "typescript": "typescript", ".ts": "typescript", ".tsx": "typescript",
        "javascript": "javascript", " js ": "javascript",
        "python": "python", ".py": "python",
        "c#": "csharp", "csharp": "csharp",
        "java ": "java", "kotlin": "kotlin",
        " go ": "go", "golang": "go",
        "rust": "rust", "php": "php",
    }
    for kw, key in lang_map.items():
        if kw in message:
            add(key)
            break

    fw_map = {
        "react": "react", "next.js": "nextjs", "nextjs": "nextjs",
        "vue": "vue", "fastapi": "fastapi", "django": "django",
        "flask": "flask", "express": "express", "nestjs": "nestjs",
    }
    for kw, key in fw_map.items():
        if kw in message:
            add(key)

    db_map = {
        "postgresql": "postgresql", "postgres": "postgresql",
        "mysql": "mysql", "mongodb": "mongodb", "redis": "redis",
    }
    for kw, key in db_map.items():
        if kw in message:
            add(key)

    cloud_map = {
        "aws": "aws", "azure": "azure", "gcp": "gcp",
        "docker": "docker", "kubernetes": "kubernetes",
    }
    for kw, key in cloud_map.items():
        if kw in message:
            add(key)

    if any(k in message for k in ["security", "auth", "jwt", "oauth", "owasp"]):
        add("owasp")
        add("auth_security")

    if any(k in message for k in ["langgraph", "langchain", "rag", "embedding", "agent"]):
        add("langgraph")
        add("rag")

    if any(k in message for k in ["clean architecture", "ddd", "microservice", "solid"]):
        add("clean_architecture")

    if any(k in message for k in ["pytest", "unit test", "jest", "vitest"]):
        add("unit_testing")

    # Always include truthfulness and output standards
    add("truthfulness_core")
    add("output_standards")

    return selected


# ── Composer ──────────────────────────────────────────────────────────────────

class DynamicPromptComposer(AbstractPromptComposer):
    """
    Builds the system prompt from a PromptPlan.
    Every section is derived from analysis — no static templates.
    """

    def __init__(self, prompt_engine: PromptIntelligenceEngine | None = None) -> None:
        self._prompt_engine = prompt_engine or get_prompt_intelligence_engine()

    def compose(self, context: IntelligenceContext) -> tuple[str, list[str]]:
        """
        Returns (system_prompt, modules_used).
        """
        # Run the Prompt Intelligence Engine
        plan = self._prompt_engine.plan(context)

        sections: list[str] = []
        modules_used: list[str] = list(plan.modules_applied)

        def add(key: str, text: str) -> None:
            if text.strip():
                sections.append(text.strip())
                modules_used.append(key)

        # 1. Identity
        add("identity", _build_identity())

        # 2. Personality principles (behavioural, not scripted)
        add("personality", _build_personality_section(plan.personality_principles))

        # 3. Response strategy
        add("strategy", _build_strategy_section(context.strategy))

        # 4. Depth instruction (from PromptPlan — dynamic, not hardcoded)
        add("depth", plan.depth.depth_instruction)

        # 5. Conversation continuity (only when relevant)
        if plan.resolved_context.continuity_note:
            add("continuity", _build_continuity_section(plan.resolved_context.continuity_note))

        # 6. Policy warnings
        add("policy", _build_policy_section(context))

        # 7. Domain modules (only when relevant to the actual message)
        domain_keys = _select_domain_modules(context)
        for key in domain_keys:
            fragment = _get_domain_registry().get(key, "")
            add(f"domain:{key}", fragment)

        # 8. Long-term memory
        add("memory", _build_memory_section(context))

        # 9. Code context
        add("code_context", _build_code_context_section(context))

        # 10. Tool results
        add("tool_results", _build_tool_results_section(context))

        return "\n\n".join(sections), modules_used

    def compose_prompt(self, context: IntelligenceContext) -> str:
        prompt, _ = self.compose(context)
        return prompt


# ── Singleton ─────────────────────────────────────────────────────────────────

_composer: DynamicPromptComposer | None = None


def get_dynamic_prompt_composer() -> DynamicPromptComposer:
    global _composer
    if _composer is None:
        _composer = DynamicPromptComposer()
    return _composer
