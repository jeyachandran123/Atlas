"""
Dynamic Prompt Composer.

Builds a structured system prompt from modular fragments.
There is no single static system prompt. Every request generates a different prompt.

Inputs:
- IntelligenceContext (intent, complexity, strategy, persona, policy, retrieved knowledge)

Output:
- A structured system prompt string
- A list of module keys used (for observability)

Design:
- Each prompt section is an independent fragment
- Fragments are selected based on context, never hardcoded
- No duplication — each fragment appears at most once
- The existing REGISTRY from app.prompts.registry is reused for domain modules
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
from app.intelligence.strategy.planner import STRATEGY_REGISTRY


def _get_domain_registry() -> dict:
    """Lazy import — avoids pulling in the full prompt module chain at import time."""
    from app.prompts.registry import REGISTRY
    return REGISTRY


# ── Prompt Section Builders ───────────────────────────────────────────────────


def _build_identity_section() -> str:
    return (
        "You are Atlas, an AI engineering platform. "
        "You are not a generic chatbot. You are a specialized engineering intelligence "
        "built to help software teams design, build, debug, and understand software systems."
    )


def _build_persona_section(persona: Persona) -> str:
    definition = _PERSONAS.get(persona)
    if not definition:
        return ""
    return definition.prompt_fragment


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


def _build_conversation_section(context: IntelligenceContext) -> str:
    conv = context.conversation
    if not conv.is_continuation:
        return ""
    parts = [f"This is a continuation of an ongoing conversation. Turn type: {conv.turn_type.value}."]
    if conv.prior_context_summary:
        parts.append(f"Prior context: {conv.prior_context_summary[:150]}")
    if conv.assumptions:
        parts.append("Established context: " + "; ".join(conv.assumptions[:3]))
    return " ".join(parts)


def _build_complexity_section(context: IntelligenceContext) -> str:
    c = context.complexity
    return (
        f"Response depth: {c.reasoning_depth}. "
        f"Expected length: {c.expected_response_length}. "
        f"Token budget: {c.expected_token_budget} tokens."
    )


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
    """
    Select domain-specific prompt modules from the existing REGISTRY
    based on detected context in the message.
    """
    registry = _get_domain_registry()
    message = context.user_message.lower()
    selected: list[str] = []
    seen: set[str] = set()

    def add(key: str) -> None:
        if key not in seen and key in registry:
            seen.add(key)
            selected.append(key)

    # Language detection
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
            break  # one language module is enough

    # Framework detection
    fw_map = {
        "react": "react", "next.js": "nextjs", "nextjs": "nextjs",
        "vue": "vue", "fastapi": "fastapi", "django": "django",
        "flask": "flask", "express": "express", "nestjs": "nestjs",
    }
    for kw, key in fw_map.items():
        if kw in message:
            add(key)

    # Database detection
    db_map = {
        "postgresql": "postgresql", "postgres": "postgresql",
        "mysql": "mysql", "mongodb": "mongodb", "redis": "redis",
    }
    for kw, key in db_map.items():
        if kw in message:
            add(key)

    # Cloud/infra detection
    cloud_map = {
        "aws": "aws", "azure": "azure", "gcp": "gcp",
        "docker": "docker", "kubernetes": "kubernetes",
    }
    for kw, key in cloud_map.items():
        if kw in message:
            add(key)

    # Security
    if any(k in message for k in ["security", "auth", "jwt", "oauth", "owasp"]):
        add("owasp")
        add("auth_security")

    # AI/agents
    if any(k in message for k in ["langgraph", "langchain", "rag", "embedding", "agent"]):
        add("langgraph")
        add("rag")

    # Architecture
    if any(k in message for k in ["clean architecture", "ddd", "microservice", "solid"]):
        add("clean_architecture")

    # Testing
    if any(k in message for k in ["pytest", "unit test", "jest", "vitest"]):
        add("unit_testing")

    # Always include truthfulness
    add("truthfulness_core")
    add("output_standards")

    return selected


# ── Composer ──────────────────────────────────────────────────────────────────


class DynamicPromptComposer(AbstractPromptComposer):
    """
    Builds a structured system prompt from modular fragments.
    Every request produces a different prompt.
    """

    def compose(self, context: IntelligenceContext) -> tuple[str, list[str]]:
        """
        Returns (system_prompt, modules_used).
        modules_used is for observability.
        """
        sections: list[str] = []
        modules_used: list[str] = []

        def add_section(key: str, text: str) -> None:
            if text.strip():
                sections.append(text.strip())
                modules_used.append(key)

        # 1. Identity (always)
        add_section("identity", _build_identity_section())

        # 2. Persona
        add_section("persona", _build_persona_section(context.persona))

        # 3. Response strategy
        add_section("strategy", _build_strategy_section(context.strategy))

        # 4. Complexity guidance
        add_section("complexity", _build_complexity_section(context))

        # 5. Conversation continuity
        add_section("conversation", _build_conversation_section(context))

        # 6. Policy warnings
        add_section("policy", _build_policy_section(context))

        # 7. Domain modules from existing registry
        domain_keys = _select_domain_modules(context)
        for key in domain_keys:
            fragment = _get_domain_registry().get(key, "")
            add_section(f"domain:{key}", fragment)

        # 8. Long-term memory
        add_section("memory", _build_memory_section(context))

        # 9. Code context
        add_section("code_context", _build_code_context_section(context))

        # 10. Tool results
        add_section("tool_results", _build_tool_results_section(context))

        return "\n\n".join(sections), modules_used

    # Satisfy the abstract interface (returns just the prompt string)
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
