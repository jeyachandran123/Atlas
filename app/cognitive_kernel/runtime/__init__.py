"""UnityWorks Cognitive Runtime & Execution Pipeline.

Built on top of the Cognitive Kernel Foundation (``app.cognitive_kernel``). The
runtime executes cognitive work but performs NO cognition — it is the process
scheduler, execution manager, and orchestration layer of the artificial mind.

Public API (curated). Depend on the abstractions in :mod:`.contracts`.
"""

from __future__ import annotations

from .budget import BudgetManager, RuntimeBudget
from .contracts import (
    BudgetSpec,
    ExecutableEngine,
    ExecutionPolicy,
    ExecutionRequest,
    ExecutionResult,
    ExecutionSnapshot,
    ExecutionState,
    QueueKind,
    RecoveryStrategy,
    RuntimeApi,
    RuntimeHealth,
    RuntimeHealthReport,
    RuntimeLifecycleState,
    RuntimeMetricsSnapshot,
)
from .errors import (
    BudgetExceeded,
    EngineNotFound,
    ExecutionCancelled,
    ExecutionError,
    ExecutionTimeout,
    IllegalExecutionTransition,
    PolicyViolation,
    RuntimeFault,
    RuntimeStateError,
)
from .manager import CognitiveRuntime, RuntimeConfig, RuntimeExecutionHandle
from .policies import PolicyRegistry

__all__ = [
    "CognitiveRuntime",
    "RuntimeConfig",
    "RuntimeExecutionHandle",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionSnapshot",
    "ExecutionState",
    "ExecutionPolicy",
    "ExecutableEngine",
    "BudgetSpec",
    "BudgetManager",
    "RuntimeBudget",
    "QueueKind",
    "RecoveryStrategy",
    "RuntimeApi",
    "RuntimeHealth",
    "RuntimeHealthReport",
    "RuntimeLifecycleState",
    "RuntimeMetricsSnapshot",
    "PolicyRegistry",
    # errors
    "RuntimeFault",
    "ExecutionError",
    "IllegalExecutionTransition",
    "BudgetExceeded",
    "ExecutionCancelled",
    "ExecutionTimeout",
    "PolicyViolation",
    "EngineNotFound",
    "RuntimeStateError",
]
