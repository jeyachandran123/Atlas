"""Executive security — the authority gate (ExL1).

Only the Executive Mind may authorize cognition and world-action, and only
sufficiently-authorized contexts may change *how the executive governs* (enact
policy, evolve configuration — ExL29). Routine governance passes are the engine
doing its job and are open; privileged governance changes require authority.
Escalation and Ask-User are never gated (ExL14: the human path is always open).
"""

from __future__ import annotations

from typing import Any

from .contracts import ExecutiveConfig
from .errors import ExecutiveSecurityError

# Governance acts that mutate *how the executive governs* — gated (ExL29).
_PRIVILEGED = frozenset({"enact_policy", "retire_policy", "set_config", "override"})


class ExecutiveSecurity:
    def __init__(self, config: ExecutiveConfig) -> None:
        self._config = config

    def _scopes(self, context: Any) -> frozenset[str]:
        sec = getattr(context, "security", None)
        return getattr(sec, "scopes", frozenset()) if sec is not None else frozenset()

    def is_authorized(self, context: Any) -> bool:
        scopes = self._scopes(context)
        return self._config.admin_scope in scopes or self._config.executive_scope in scopes

    def require_authority(self, action: str, context: Any) -> None:
        if action in _PRIVILEGED and not self.is_authorized(context):
            raise ExecutiveSecurityError(
                f"Executive act {action!r} requires governance authority "
                f"({self._config.executive_scope!r} or {self._config.admin_scope!r})."
            )
