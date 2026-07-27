"""Runtime error hierarchy (extends the kernel's ``KernelError``)."""

from __future__ import annotations

from ..errors import KernelError


class RuntimeFault(KernelError):
    """Root of runtime-layer errors."""


class ExecutionError(RuntimeFault):
    """An execution failed during the pipeline."""


class IllegalExecutionTransition(RuntimeFault):
    """An invalid execution-state transition was attempted (RL3)."""


class BudgetExceeded(RuntimeFault):
    """An execution exceeded its runtime-enforced budget (P3/P5)."""


class ExecutionCancelled(RuntimeFault):
    """The execution was cancelled cooperatively."""


class ExecutionTimeout(RuntimeFault):
    """The execution exceeded its time budget/timeout policy."""


class PolicyViolation(RuntimeFault):
    """An operation violated a runtime execution policy."""


class EngineNotFound(RuntimeFault):
    """No executable engine is registered for the requested name."""


class RuntimeStateError(RuntimeFault):
    """The runtime is not in a state that permits the requested operation."""
