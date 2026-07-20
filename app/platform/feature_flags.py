"""
Enterprise Feature Flag architecture (Objective 6). Architecture only — no
management UI, no persistence layer yet, matching the request exactly.

Scope precedence, most to least specific:
    user > department > tenant > workspace > environment > global

The spec's scope list included "Restaurant" — a vertical-template artifact
(this platform has no restaurant domain concept). It's generalized here as
`DEPARTMENT`, which is what it was standing in for; no behavior is lost.

Evaluation goes through FeatureFlagService.is_enabled(key, context) — never
a hardcoded `if` on environment or org id. Today's provider is static/env-
driven; swapping in a DB-backed provider later means implementing
FlagProvider once — no caller changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class FlagScope(str, Enum):
    GLOBAL = "global"
    ENVIRONMENT = "environment"
    WORKSPACE = "workspace"
    TENANT = "tenant"
    DEPARTMENT = "department"
    USER = "user"


# Precedence order — first match wins when evaluating.
_SCOPE_PRECEDENCE: tuple[FlagScope, ...] = (
    FlagScope.USER,
    FlagScope.DEPARTMENT,
    FlagScope.TENANT,
    FlagScope.WORKSPACE,
    FlagScope.ENVIRONMENT,
    FlagScope.GLOBAL,
)


@dataclass(frozen=True)
class FlagContext:
    """The scopes an evaluation request belongs to — any subset may be set."""
    environment: Optional[str] = None
    workspace_id: Optional[str] = None
    tenant_id: Optional[str] = None
    department: Optional[str] = None
    user_id: Optional[str] = None

    def key_for(self, scope: FlagScope) -> Optional[str]:
        return {
            FlagScope.ENVIRONMENT: self.environment,
            FlagScope.WORKSPACE: self.workspace_id,
            FlagScope.TENANT: self.tenant_id,
            FlagScope.DEPARTMENT: self.department,
            FlagScope.USER: self.user_id,
            FlagScope.GLOBAL: "*",
        }.get(scope)


@dataclass(frozen=True)
class FeatureFlag:
    key: str
    description: str = ""
    default_enabled: bool = False


class FlagProvider(ABC):
    """Where flag overrides come from. Swap this, not the service."""

    @abstractmethod
    def get_override(self, flag_key: str, scope: FlagScope, scope_value: str) -> Optional[bool]:
        """Return an explicit True/False override, or None if unset at this scope."""


class StaticFlagProvider(FlagProvider):
    """In-memory/config-driven provider. Sufficient until a DB-backed one exists."""

    def __init__(self) -> None:
        self._overrides: dict[tuple[str, FlagScope, str], bool] = {}

    def set_override(self, flag_key: str, scope: FlagScope, scope_value: str, enabled: bool) -> None:
        self._overrides[(flag_key, scope, scope_value)] = enabled

    def get_override(self, flag_key: str, scope: FlagScope, scope_value: str) -> Optional[bool]:
        return self._overrides.get((flag_key, scope, scope_value))


# Known platform flags — registering a flag does not enable it; it documents
# the default and gives dashboards/consumers a discoverable list.
_FLAGS: dict[str, FeatureFlag] = {
    f.key: f for f in (
        FeatureFlag("ocr_enabled", "Run real OCR extraction (vs. the null provider)", default_enabled=False),
        FeatureFlag("financial_parser_enabled", "Use the financial-documents processing profile", default_enabled=False),
        FeatureFlag("vision_ai_enabled", "Vision AI subsystem", default_enabled=True),
        FeatureFlag("repository_ai_enabled", "Repository-native AI engineer mode", default_enabled=True),
        FeatureFlag("experimental_retrieval_enabled", "Embedding-backed retrieval (Phase 3+)", default_enabled=False),
    )
}


class FeatureFlagService:
    def __init__(self, provider: Optional[FlagProvider] = None) -> None:
        self._provider = provider or StaticFlagProvider()

    def is_enabled(self, flag_key: str, context: Optional[FlagContext] = None) -> bool:
        flag = _FLAGS.get(flag_key)
        context = context or FlagContext()
        for scope in _SCOPE_PRECEDENCE:
            scope_value = context.key_for(scope)
            if scope_value is None:
                continue
            override = self._provider.get_override(flag_key, scope, scope_value)
            if override is not None:
                return override
        return flag.default_enabled if flag else False

    def list_flags(self) -> list[FeatureFlag]:
        return sorted(_FLAGS.values(), key=lambda f: f.key)


_service: FeatureFlagService | None = None


def get_feature_flag_service() -> FeatureFlagService:
    global _service
    if _service is None:
        _service = FeatureFlagService()
    return _service
