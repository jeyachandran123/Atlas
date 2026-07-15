"""
Dynamic Prompt Composer.

Composes a system prompt at runtime by selecting and assembling
relevant prompt modules based on AgentState.

Design:
- Single Responsibility: only composes prompts, nothing else
- Open/Closed: extend by adding new detector methods, not modifying existing ones
- Dependency Inversion: depends on REGISTRY abstraction, not module files
- No duplication: deduplication via ordered set before joining

Flow:
    AgentState → PromptComposer.compose() → composed system_prompt string

The composed prompt is stored in state["system_prompt"] and used by
CodingAgent instead of the old static SYSTEM_PROMPTS dict.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.intelligence.context.keywords import (
    LANG_MAP as _LANGUAGE_KEYWORDS,
    FRAMEWORK_MAP as _FRAMEWORK_KEYWORDS,
    DB_MAP as _DATABASE_KEYWORDS,
    CLOUD_MAP as _CLOUD_KEYWORDS,
    BUSINESS_MAP as _BUSINESS_KEYWORDS,
    SECURITY_MAP as _SECURITY_KEYWORDS,
    AI_MAP as _AI_KEYWORDS,
    ARCH_MAP as _ARCHITECTURE_KEYWORDS,
    TEST_MAP as _TESTING_KEYWORDS,
    FACTUAL_KW as _FACTUAL_TRIGGERS,
)
from app.prompts.registry import REGISTRY

if TYPE_CHECKING:
    from app.agents.state import AgentState

# ── Intent → base persona mapping ─────────────────────────────────────────────

_INTENT_PERSONAS: dict[str, list[str]] = {
    "code":     ["engineer", "architect", "planner"],
    "fix":      ["engineer", "debugger"],
    "review":   ["reviewer", "security_expert"],
    "explain":  ["mentor", "documentation"],
    "test":     ["tester", "engineer"],
    "search":   ["engineer"],
    "chat":     ["mentor"],
}

# ── Agent mode → base persona mapping ─────────────────────────────────────────

_MODE_PERSONAS: dict[str, list[str]] = {
    "auto":     ["mentor"],
    "code":     ["engineer", "architect"],
    "business": ["business"],
}

# ── Truthfulness modules always included ──────────────────────────────────────

_ALWAYS_INCLUDE = [
    "output_standards",
    "truthfulness_core",
    "base_truthfulness",
]



class PromptComposer:
    """
    Dynamically composes a system prompt from modular components.

    Called as a LangGraph node:
        state = await composer.compose(state)

    The composed prompt is stored in state["system_prompt"].
    """

    def compose(self, state: "AgentState") -> str:
        """
        Build and return the composed system prompt.
        Deduplicates modules — each module appears at most once.
        """
        message = state.get("user_message", "").lower()
        intent = state.get("intent", "chat")
        agent_mode = state.get("agent_mode", "auto")

        # Ordered set — preserves insertion order, prevents duplicates
        selected: list[str] = []
        seen: set[str] = set()

        def add(key: str) -> None:
            if key not in seen and key in REGISTRY:
                seen.add(key)
                selected.append(key)

        # 1. Mode-based base personas
        for key in _MODE_PERSONAS.get(agent_mode, ["mentor"]):
            add(key)

        # 2. Intent-based personas (code mode only — auto/business use mode personas)
        if agent_mode == "code":
            for key in _INTENT_PERSONAS.get(intent, ["engineer"]):
                add(key)

        # 3. Auto-detect from message content
        for keyword, module_key in _FRAMEWORK_KEYWORDS.items():
            if keyword in message:
                add(module_key)

        for keyword, module_key in _LANGUAGE_KEYWORDS.items():
            if keyword in message:
                add(module_key)

        for keyword, module_key in _DATABASE_KEYWORDS.items():
            if keyword in message:
                add(module_key)

        for keyword, module_key in _CLOUD_KEYWORDS.items():
            if keyword in message:
                add(module_key)

        # Business mode: always add business domain modules
        if agent_mode == "business":
            for keyword, module_key in _BUSINESS_KEYWORDS.items():
                if keyword in message:
                    add(module_key)
            # If no specific business domain detected, add general business
            if not any(k in seen for k in ["hotel", "erp", "pos", "inventory", "hrms", "crm", "finance"]):
                add("business")

        for keyword, module_key in _SECURITY_KEYWORDS.items():
            if keyword in message:
                add(module_key)

        for keyword, module_key in _AI_KEYWORDS.items():
            if keyword in message:
                add(module_key)

        for keyword, module_key in _ARCHITECTURE_KEYWORDS.items():
            if keyword in message:
                add(module_key)

        for keyword, module_key in _TESTING_KEYWORDS.items():
            if keyword in message:
                add(module_key)

        # 4. Factual topics → add chronology + entity validation
        if any(trigger in message for trigger in _FACTUAL_TRIGGERS):
            add("chronology_validation")
            add("entity_validation")
            add("fact_verification")

        # 5. Always-included modules (output standards + truthfulness core)
        for key in _ALWAYS_INCLUDE:
            add(key)

        # 6. Assemble — join with double newline separator
        parts = [REGISTRY[key] for key in selected]
        return "\n\n".join(parts)


# ── Module-level singleton ────────────────────────────────────────────────────
_composer: PromptComposer | None = None


def get_composer() -> PromptComposer:
    global _composer
    if _composer is None:
        _composer = PromptComposer()
    return _composer
