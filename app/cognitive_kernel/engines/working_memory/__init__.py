"""UnityWorks Working Memory Engine — the first true cognitive engine.

The bounded conscious workspace. It activates *references* to cognitive objects
(never copies), is capacity-bounded (CL1/P3), ephemeral (activation decays), and
reads/writes only through the Cognitive State Manager. Attention decides what
enters it; Reasoning operates on it; Executive manages goals within it. It owns
none of that behaviour.
"""

from __future__ import annotations

from .api import WorkingMemoryRuntimeApi
from .contracts import (
    Slot,
    WMConfig,
    WMHealthReport,
    WMMetricsSnapshot,
    WMSnapshot,
    WorkingMemoryApi,
    WorkspaceInfo,
    WorkspaceKind,
    Zone,
)
from .engine import WorkingMemoryEngine
from .errors import (
    CapacityViolation,
    MissingTargetError,
    UnknownOperationError,
    UnknownWorkspaceError,
    WorkingMemoryError,
    WorkingMemorySecurityError,
)

__all__ = [
    "WorkingMemoryEngine",
    "WorkingMemoryRuntimeApi",
    "WorkingMemoryApi",
    "WMConfig",
    "Zone",
    "WorkspaceKind",
    "WorkspaceInfo",
    "Slot",
    "WMSnapshot",
    "WMMetricsSnapshot",
    "WMHealthReport",
    # errors
    "WorkingMemoryError",
    "UnknownWorkspaceError",
    "MissingTargetError",
    "CapacityViolation",
    "WorkingMemorySecurityError",
    "UnknownOperationError",
]
