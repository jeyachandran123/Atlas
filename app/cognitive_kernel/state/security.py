"""State security — access control over reads/writes (P4/P10 boundary).

Guards state access by the execution context's scopes. Immutable-object
*evolution* (Identity Core / Executive Decision) always requires the ``state:admin``
scope, independent of the ``enforce`` flag, because that is a constitutionally
gated path (DeL1/ExL12). Ordinary read/write enforcement is configurable so that
internal engines can operate without ceremony while enterprise deployments can
lock it down.
"""

from __future__ import annotations

from ..contracts import SecurityContext
from .contracts import ObjectType
from .errors import StateSecurityError

READ = "state:read"
WRITE = "state:write"
ADMIN = "state:admin"


class StateSecurity:
    def __init__(self, enforce: bool = False) -> None:
        self._enforce = enforce

    def _has(self, security: SecurityContext, scope: str) -> bool:
        return scope in security.scopes or ADMIN in security.scopes

    def check_read(self, security: SecurityContext) -> None:
        if self._enforce and not self._has(security, READ):
            raise StateSecurityError(f"{security.principal!r} lacks {READ}")

    def check_write(self, security: SecurityContext) -> None:
        if self._enforce and not self._has(security, WRITE):
            raise StateSecurityError(f"{security.principal!r} lacks {WRITE}")

    def check_admin(self, security: SecurityContext) -> None:
        # Always enforced: gated constitutional paths (immutable evolution, rollback of Core).
        if ADMIN not in security.scopes:
            raise StateSecurityError(
                f"{security.principal!r} lacks {ADMIN} (required for gated state operations)"
            )

    def guards_immutable_evolution(self, security: SecurityContext, type: ObjectType) -> None:
        # Evolving an immutable object is only permitted under admin authority.
        self.check_admin(security)
