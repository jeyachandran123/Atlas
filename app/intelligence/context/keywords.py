"""
Shared keyword maps for context detection.

Single source of truth — imported by orchestrator, prompt composers,
and any other module that needs keyword-based detection.
Eliminates the three duplicate copies that previously existed in:
  - agents/orchestrator.py
  - prompts/composer.py
  - intelligence/prompt/composer.py
"""

from __future__ import annotations

LANG_MAP: dict[str, str] = {
    "typescript": "typescript", ".tsx": "typescript", ".ts ": "typescript",
    "javascript": "javascript", " js ": "javascript",
    "python": "python", ".py": "python",
    "c#": "csharp", "csharp": "csharp",
    "java ": "java", "kotlin": "kotlin",
    " go ": "go", "golang": "go",
    "rust": "rust", "php": "php", "swift": "swift", "dart": "dart",
}

FRAMEWORK_MAP: dict[str, str] = {
    "react": "react", "next.js": "nextjs", "nextjs": "nextjs",
    "vue": "vue", "nuxt": "nuxtjs", "angular": "angular", "svelte": "svelte",
    "react native": "react_native", "flutter": "flutter",
    "fastapi": "fastapi", "django": "django", "flask": "flask",
    "express": "express", "nestjs": "nestjs", "nest.js": "nestjs",
    "asp.net": "aspnet", "spring boot": "spring_boot", "laravel": "laravel",
}

DB_MAP: dict[str, str] = {
    "postgresql": "postgresql", "postgres": "postgresql",
    "mysql": "mysql", "sql server": "mssql", "mssql": "mssql",
    "mongodb": "mongodb", "mongo": "mongodb",
    "redis": "redis", "elasticsearch": "elasticsearch",
    "dynamodb": "dynamodb", "firestore": "firebase_db", "firebase": "firebase_db",
    "sql": "sql",
}

CLOUD_MAP: dict[str, str] = {
    "aws": "aws", "amazon web": "aws",
    "azure": "azure", "google cloud": "gcp", "gcp": "gcp",
    "docker": "docker", "kubernetes": "kubernetes", "k8s": "kubernetes",
    "terraform": "terraform", "github actions": "github_actions",
    "ci/cd": "cicd", "cicd": "cicd",
}

BUSINESS_MAP: dict[str, str] = {
    "hotel": "hotel", "pms": "hotel", "reservation": "hotel",
    "check-in": "hotel", "revpar": "hotel",
    "erp": "erp", "procurement": "erp", "purchase order": "erp", "grn": "erp",
    "pos": "pos", "point of sale": "pos", "cashier": "pos",
    "inventory": "inventory", "warehouse": "inventory", "stock": "inventory", "sku": "inventory",
    "payroll": "hrms", "hrms": "hrms", "leave": "hrms",
    "crm": "crm", "lead": "crm",
    "finance": "finance", "accounting": "finance", "ledger": "finance", "invoice": "finance",
}

ARCH_MAP: dict[str, str] = {
    "clean architecture": "clean_architecture",
    "domain driven": "ddd", "ddd": "ddd",
    "microservice": "microservices",
    "event driven": "event_driven", "event sourcing": "event_driven", "cqrs": "event_driven",
    "solid": "solid",
}

TEST_MAP: dict[str, str] = {
    "unit test": "unit_testing", "integration test": "integration_testing",
    "e2e": "e2e_testing", "playwright": "e2e_testing", "cypress": "e2e_testing",
    "pytest": "pytest", "jest": "unit_testing", "vitest": "unit_testing",
}

_AUTH_LABEL: str = "auth" + "_security"
_API_LABEL: str = "api" + "_security"

SECURITY_MAP: dict[str, str] = {
    "security": "owasp", "owasp": "owasp",
    "authentication": _AUTH_LABEL, "auth": _AUTH_LABEL,
    "jwt": _AUTH_LABEL, "oauth": _AUTH_LABEL,
    "injection": "secure_coding", "xss": "secure_coding", "csrf": "secure_coding",
    "vulnerability": "owasp", "api key": _API_LABEL, "rate limit": _API_LABEL,
}

AI_MAP: dict[str, str] = {
    "langgraph": "langgraph", "langchain": "langchain",
    "rag": "rag", "retrieval": "rag",
    "embedding": "vector_db", "vector": "vector_db", "chroma": "vector_db",
    "multi-agent": "multi_agent", "multi agent": "multi_agent",
    "ollama": "ollama", "llm": "prompt_engineering",
    "prompt": "prompt_engineering", "agent": "langgraph",
}

FACTUAL_KW: list[str] = [
    "when was", "what year", "released", "published", "version",
    "history", "invented", "created", "founded", "launched",
    "book", "movie", "show", "season", "episode",
]

SECURITY_KW: list[str] = list(SECURITY_MAP.keys())
AI_KW: list[str] = list(AI_MAP.keys())


def first_match(lower: str, mapping: dict[str, str]) -> str:
    """Return the first matching value from a keyword map, or empty string."""
    for kw, val in mapping.items():
        if kw in lower:
            return val
    return ""
