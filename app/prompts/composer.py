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

import re
from typing import TYPE_CHECKING

from app.prompts.registry import REGISTRY

if TYPE_CHECKING:
    from app.agents.state import AgentState


# ── Keyword → module key mappings ─────────────────────────────────────────────
# These drive automatic detection from the user message.

_FRAMEWORK_KEYWORDS: dict[str, str] = {
    # Frontend
    "react":         "react",
    "next.js":       "nextjs",
    "nextjs":        "nextjs",
    "vue":           "vue",
    "nuxt":          "nuxtjs",
    "angular":       "angular",
    "svelte":        "svelte",
    "react native":  "react_native",
    "flutter":       "flutter",
    # Backend
    "fastapi":       "fastapi",
    "django":        "django",
    "flask":         "flask",
    "express":       "express",
    "nestjs":        "nestjs",
    "nest.js":       "nestjs",
    "asp.net":       "aspnet",
    "spring boot":   "spring_boot",
    "laravel":       "laravel",
}

_LANGUAGE_KEYWORDS: dict[str, str] = {
    "typescript":    "typescript",
    " ts ":          "typescript",
    ".tsx":          "typescript",
    ".ts":           "typescript",
    "javascript":    "javascript",
    " js ":          "javascript",
    "python":        "python",
    " py ":          "python",
    ".py":           "python",
    "c#":            "csharp",
    "csharp":        "csharp",
    "java ":         "java",
    "kotlin":        "kotlin",
    " go ":          "go",
    "golang":        "go",
    "rust":          "rust",
    "php":           "php",
    "swift":         "swift",
    "dart":          "dart",
}

_DATABASE_KEYWORDS: dict[str, str] = {
    "postgresql":    "postgresql",
    "postgres":      "postgresql",
    "mysql":         "mysql",
    "sql server":    "mssql",
    "mssql":         "mssql",
    "mongodb":       "mongodb",
    "mongo":         "mongodb",
    "redis":         "redis",
    "elasticsearch": "elasticsearch",
    "dynamodb":      "dynamodb",
    "firestore":     "firebase_db",
    "firebase":      "firebase_db",
    "sql":           "sql",
}

_CLOUD_KEYWORDS: dict[str, str] = {
    "aws":           "aws",
    "amazon":        "aws",
    "azure":         "azure",
    "google cloud":  "gcp",
    "gcp":           "gcp",
    "docker":        "docker",
    "kubernetes":    "kubernetes",
    "k8s":           "kubernetes",
    "terraform":     "terraform",
    "github actions":"github_actions",
    "ci/cd":         "cicd",
    "cicd":          "cicd",
}

_BUSINESS_KEYWORDS: dict[str, str] = {
    "hotel":         "hotel",
    "pms":           "hotel",
    "reservation":   "hotel",
    "check-in":      "hotel",
    "checkout":      "hotel",
    "revpar":        "hotel",
    "erp":           "erp",
    "procurement":   "erp",
    "purchase order":"erp",
    "grn":           "erp",
    "pos":           "pos",
    "point of sale": "pos",
    "cashier":       "pos",
    "inventory":     "inventory",
    "warehouse":     "inventory",
    "stock":         "inventory",
    "sku":           "inventory",
    "payroll":       "hrms",
    "hrms":          "hrms",
    "leave":         "hrms",
    "crm":           "crm",
    "lead":          "crm",
    "finance":       "finance",
    "accounting":    "finance",
    "ledger":        "finance",
    "invoice":       "finance",
}

_SECURITY_KEYWORDS: dict[str, str] = {
    "security":      "owasp",
    "owasp":         "owasp",
    "authentication":"auth_security",
    "auth":          "auth_security",
    "jwt":           "auth_security",
    "oauth":         "auth_security",
    "injection":     "secure_coding",
    "xss":           "secure_coding",
    "csrf":          "secure_coding",
    "vulnerability": "owasp",
    "api key":       "api_security",
    "rate limit":    "api_security",
}

_AI_KEYWORDS: dict[str, str] = {
    "langgraph":     "langgraph",
    "langchain":     "langchain",
    "rag":           "rag",
    "retrieval":     "rag",
    "embedding":     "vector_db",
    "vector":        "vector_db",
    "chroma":        "vector_db",
    "multi-agent":   "multi_agent",
    "multi agent":   "multi_agent",
    "ollama":        "ollama",
    "llm":           "prompt_engineering",
    "prompt":        "prompt_engineering",
    "agent":         "langgraph",
}

_ARCHITECTURE_KEYWORDS: dict[str, str] = {
    "clean architecture": "clean_architecture",
    "ddd":                "ddd",
    "domain driven":      "ddd",
    "microservice":       "microservices",
    "event driven":       "event_driven",
    "event sourcing":     "event_driven",
    "cqrs":               "event_driven",
    "solid":              "solid",
}

_TESTING_KEYWORDS: dict[str, str] = {
    "unit test":     "unit_testing",
    "integration test": "integration_testing",
    "e2e":           "e2e_testing",
    "playwright":    "e2e_testing",
    "cypress":       "e2e_testing",
    "pytest":        "pytest",
    "jest":          "unit_testing",
    "vitest":        "unit_testing",
}

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

# ── Truthfulness modules for factual/general topics ───────────────────────────

_FACTUAL_TRIGGERS = [
    "when was", "what year", "released", "published", "version",
    "history", "invented", "created", "founded", "launched",
    "book", "movie", "show", "season", "episode",
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
