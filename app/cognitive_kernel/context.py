"""Execution-context factory.

Nothing executes without an :class:`ExecutionContext`. The factory stamps a
fresh correlation id and trace, binds the (immutable) identity, and attaches a
budget, cancellation token, and security context. Engines receive this factory
via :class:`KernelServices` and derive child contexts for sub-operations.
"""

from __future__ import annotations

import uuid

from .contracts import (
    ExecutionBudget,
    ExecutionContext,
    IdentityProvider,
    SecurityContext,
    TraceInfo,
)


class ContextFactory:
    def __init__(self, identity: IdentityProvider) -> None:
        self._identity = identity

    def new(
        self,
        *,
        security: SecurityContext,
        workspace_id: str | None = None,
        conversation_id: str | None = None,
        current_goal_id: str | None = None,
        active_engine: str | None = None,
        budget: ExecutionBudget | None = None,
        correlation_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> ExecutionContext:
        cid = correlation_id or uuid.uuid4().hex
        trace = TraceInfo(
            trace_id=cid,
            span_id=uuid.uuid4().hex,
            parent_span_id=parent_span_id,
        )
        return ExecutionContext(
            correlation_id=cid,
            identity_id=self._identity.identity().identity_id,
            security=security,
            trace=trace,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            current_goal_id=current_goal_id,
            active_engine=active_engine,
            budget=budget or ExecutionBudget(),
        )
