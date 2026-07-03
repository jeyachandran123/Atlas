"""
Prompt Module Registry.

Single source of truth for all prompt modules.
Maps string keys → prompt text strings.

Design principles:
- Open/Closed: add new modules by adding entries here, never modifying existing ones
- Dependency Inversion: consumers depend on this registry, not on module files directly
- Single Responsibility: registry only maps keys to strings
- Lazy loading: modules imported at registry build time (once at startup)

Usage:
    from app.prompts.registry import REGISTRY
    text = REGISTRY.get("react")          # None if not found
    text = REGISTRY["react"]              # KeyError if not found
    keys = REGISTRY.keys()
"""

from __future__ import annotations

from app.prompts.modules.base.personas import (
    ARCHITECT,
    DEBUGGER,
    DEVOPS_EXPERT,
    DOCUMENTATION_EXPERT,
    ENGINEER,
    MENTOR,
    OUTPUT_STANDARDS,
    PERFORMANCE_EXPERT,
    PLANNER,
    REVIEWER,
    SECURITY_EXPERT,
    SYSTEM_DESIGNER,
    TESTER,
    TRUTHFULNESS_CORE,
)
from app.prompts.modules.frameworks.frameworks import (
    ANGULAR,
    ASPNET,
    DJANGO,
    EXPRESS,
    FASTAPI,
    FLASK,
    FLUTTER,
    LARAVEL,
    NESTJS,
    NEXTJS,
    NUXTJS,
    REACT,
    REACT_NATIVE,
    SPRING_BOOT,
    SVELTE,
    VUE,
)
from app.prompts.modules.languages.languages import (
    CSHARP,
    DART,
    GO,
    JAVA,
    JAVASCRIPT,
    KOTLIN,
    PHP,
    PYTHON,
    RUST,
    SWIFT,
    TYPESCRIPT,
)
from app.prompts.modules.databases.databases import (
    DYNAMODB,
    ELASTICSEARCH,
    FIREBASE_DB,
    MONGODB,
    MSSQL,
    MYSQL,
    POSTGRESQL,
    REDIS,
    SQL_GENERAL,
)
from app.prompts.modules.cloud.cloud import (
    AWS,
    AZURE,
    CICD,
    DOCKER,
    GCP,
    GITHUB_ACTIONS,
    KUBERNETES,
    TERRAFORM,
)
from app.prompts.modules.business.business import (
    BUSINESS_GENERAL,
    CRM,
    ERP,
    FINANCE,
    HOTEL_MANAGEMENT,
    HRMS,
    INVENTORY,
    POS,
)
from app.prompts.modules.security.security import (
    API_SECURITY,
    AUTH_SECURITY,
    OWASP,
    SECURE_CODING,
)
from app.prompts.modules.ai.ai import (
    LANGCHAIN,
    LANGGRAPH,
    MULTI_AGENT,
    OLLAMA,
    PROMPT_ENGINEERING,
    RAG,
    VECTOR_DB,
)
from app.prompts.modules.architecture.architecture import (
    CLEAN_ARCHITECTURE,
    DDD,
    EVENT_DRIVEN,
    MICROSERVICES,
    SOLID,
)
from app.prompts.modules.testing.testing import (
    E2E_TESTING,
    INTEGRATION_TESTING,
    PYTEST,
    UNIT_TESTING,
)
from app.prompts.modules.truthfulness.truthfulness import (
    BASE_TRUTHFULNESS,
    CHRONOLOGY_VALIDATION,
    ENTITY_VALIDATION,
    FACT_VERIFICATION,
    SELF_CORRECTION,
    UNCERTAINTY_HANDLING,
)

# ── Registry ──────────────────────────────────────────────────────────────────
# All keys are lowercase. Consumers use lowercase keys.

REGISTRY: dict[str, str] = {
    # Base personas
    "engineer":            ENGINEER,
    "architect":           ARCHITECT,
    "mentor":              MENTOR,
    "planner":             PLANNER,
    "reviewer":            REVIEWER,
    "debugger":            DEBUGGER,
    "tester":              TESTER,
    "security_expert":     SECURITY_EXPERT,
    "performance_expert":  PERFORMANCE_EXPERT,
    "devops_expert":       DEVOPS_EXPERT,
    "documentation":       DOCUMENTATION_EXPERT,
    "system_designer":     SYSTEM_DESIGNER,
    "output_standards":    OUTPUT_STANDARDS,
    "truthfulness_core":   TRUTHFULNESS_CORE,

    # Frontend frameworks
    "react":               REACT,
    "nextjs":              NEXTJS,
    "vue":                 VUE,
    "nuxtjs":              NUXTJS,
    "angular":             ANGULAR,
    "svelte":              SVELTE,
    "react_native":        REACT_NATIVE,
    "flutter":             FLUTTER,

    # Backend frameworks
    "fastapi":             FASTAPI,
    "django":              DJANGO,
    "flask":               FLASK,
    "express":             EXPRESS,
    "nestjs":              NESTJS,
    "aspnet":              ASPNET,
    "spring_boot":         SPRING_BOOT,
    "laravel":             LARAVEL,

    # Languages
    "typescript":          TYPESCRIPT,
    "javascript":          JAVASCRIPT,
    "python":              PYTHON,
    "csharp":              CSHARP,
    "java":                JAVA,
    "kotlin":              KOTLIN,
    "go":                  GO,
    "rust":                RUST,
    "php":                 PHP,
    "swift":               SWIFT,
    "dart":                DART,

    # Databases
    "postgresql":          POSTGRESQL,
    "mysql":               MYSQL,
    "mssql":               MSSQL,
    "mongodb":             MONGODB,
    "redis":               REDIS,
    "elasticsearch":       ELASTICSEARCH,
    "dynamodb":            DYNAMODB,
    "firebase_db":         FIREBASE_DB,
    "sql":                 SQL_GENERAL,

    # Cloud & infra
    "aws":                 AWS,
    "azure":               AZURE,
    "gcp":                 GCP,
    "docker":              DOCKER,
    "kubernetes":          KUBERNETES,
    "terraform":           TERRAFORM,
    "cicd":                CICD,
    "github_actions":      GITHUB_ACTIONS,

    # Business domains
    "business":            BUSINESS_GENERAL,
    "hotel":               HOTEL_MANAGEMENT,
    "erp":                 ERP,
    "pos":                 POS,
    "inventory":           INVENTORY,
    "finance":             FINANCE,
    "crm":                 CRM,
    "hrms":                HRMS,

    # Security
    "owasp":               OWASP,
    "auth_security":       AUTH_SECURITY,
    "api_security":        API_SECURITY,
    "secure_coding":       SECURE_CODING,

    # AI & agents
    "langgraph":           LANGGRAPH,
    "langchain":           LANGCHAIN,
    "rag":                 RAG,
    "multi_agent":         MULTI_AGENT,
    "prompt_engineering":  PROMPT_ENGINEERING,
    "ollama":              OLLAMA,
    "vector_db":           VECTOR_DB,

    # Architecture
    "clean_architecture":  CLEAN_ARCHITECTURE,
    "ddd":                 DDD,
    "microservices":       MICROSERVICES,
    "event_driven":        EVENT_DRIVEN,
    "solid":               SOLID,

    # Testing
    "unit_testing":        UNIT_TESTING,
    "integration_testing": INTEGRATION_TESTING,
    "e2e_testing":         E2E_TESTING,
    "pytest":              PYTEST,

    # Truthfulness
    "base_truthfulness":       BASE_TRUTHFULNESS,
    "fact_verification":       FACT_VERIFICATION,
    "chronology_validation":   CHRONOLOGY_VALIDATION,
    "entity_validation":       ENTITY_VALIDATION,
    "self_correction":         SELF_CORRECTION,
    "uncertainty_handling":    UNCERTAINTY_HANDLING,
}
