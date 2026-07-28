"""UnityWorks Cognitive State Manager.

The first true cognitive component: it owns the complete lifecycle of the
Cognitive State (store, protect, version, validate, restore) and performs NO
cognition. Future engines read/write the state only through this manager.
Built on the Kernel Foundation; modifies neither the kernel nor the runtime.
"""

from __future__ import annotations

from .contracts import (
    CognitiveObject,
    CommitResult,
    InvariantValidator,
    ObjectStatus,
    ObjectType,
    Region,
    RelationshipEdge,
    RelationshipType,
    StateChange,
    StateDiff,
    StateHealthReport,
    StateMetricsSnapshot,
    StateSnapshot,
)
from .errors import (
    ImmutableObjectError,
    ObjectNotFound,
    PlacementError,
    StateConflictError,
    StateConsistencyError,
    StateError,
    StateIntegrityError,
    StateSecurityError,
    TransactionError,
)
from .manager import CognitiveStateManager, StateConfig, StateLifecycle
from .security import ADMIN, READ, WRITE
from .transaction import StateTransaction

__all__ = [
    "CognitiveStateManager",
    "StateConfig",
    "StateLifecycle",
    "StateTransaction",
    "CognitiveObject",
    "ObjectType",
    "ObjectStatus",
    "Region",
    "RelationshipType",
    "RelationshipEdge",
    "CommitResult",
    "StateChange",
    "StateDiff",
    "StateSnapshot",
    "StateMetricsSnapshot",
    "StateHealthReport",
    "InvariantValidator",
    "READ",
    "WRITE",
    "ADMIN",
    # errors
    "StateError",
    "ObjectNotFound",
    "ImmutableObjectError",
    "StateConflictError",
    "StateConsistencyError",
    "StateSecurityError",
    "StateIntegrityError",
    "TransactionError",
    "PlacementError",
]
