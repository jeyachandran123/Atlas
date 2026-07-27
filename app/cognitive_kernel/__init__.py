"""UnityWorks Cognitive Kernel Foundation.

The kernel is the execution environment for every future cognitive engine — the
"Mind" above the existing platforms (which become "Faculties"). It performs no
cognition itself; it provides the runtime infrastructure that Working Memory,
Attention, Reasoning, Executive, Prediction, Meta-Cognition, Learning, and
Development engines will register into and run inside.

Public API (curated). Concrete infrastructure classes live in submodules and are
resolved via dependency injection; consumers should depend on the abstractions
in :mod:`.contracts`.
"""

from __future__ import annotations

from .bootstrap import Bootstrapper, boot
from .contracts import (
    Capability,
    Checkpoint,
    CognitiveEngine,
    CognitiveEvent,
    ConstitutionVersion,
    EngineMetadata,
    EventPriority,
    ExecutionBudget,
    ExecutionContext,
    HealthReport,
    HealthStatus,
    Identity,
    KernelServices,
    KernelState,
    Law,
    ScheduleKind,
    SecurityContext,
)
from .errors import (
    BootstrapError,
    CheckpointError,
    ConstitutionViolation,
    ContextError,
    DependencyResolutionError,
    EngineRegistrationError,
    KernelError,
    LedgerIntegrityError,
    LifecycleError,
    RecoveryError,
)
from .kernel import KERNEL_VERSION, CognitiveKernel, KernelConfig

__all__ = [
    "KERNEL_VERSION",
    "CognitiveKernel",
    "KernelConfig",
    "Bootstrapper",
    "boot",
    "KernelServices",
    "KernelState",
    "CognitiveEngine",
    "EngineMetadata",
    "CognitiveEvent",
    "EventPriority",
    "ExecutionContext",
    "ExecutionBudget",
    "SecurityContext",
    "Identity",
    "Law",
    "ConstitutionVersion",
    "Capability",
    "Checkpoint",
    "HealthReport",
    "HealthStatus",
    "ScheduleKind",
    # errors
    "KernelError",
    "LifecycleError",
    "BootstrapError",
    "ConstitutionViolation",
    "LedgerIntegrityError",
    "EngineRegistrationError",
    "DependencyResolutionError",
    "CheckpointError",
    "RecoveryError",
    "ContextError",
]
