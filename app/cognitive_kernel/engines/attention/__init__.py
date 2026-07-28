"""UnityWorks Attention Engine — the gatekeeper of consciousness.

The first decision-making cognitive engine. It evaluates cognitive candidates by
a multi-factor salience vector, runs a biased competition, selects the winning
focus coalition, inhibits the losers, and activates Working Memory — determining
what becomes conscious. It performs no reasoning, executive decision, prediction,
or learning; it only selects. Built on the Kernel, Runtime, State Manager, and
Working Memory Engine using their public contracts.
"""

from __future__ import annotations

from .contracts import (
    AttendResult,
    AttentionConfig,
    AttentionHealthReport,
    AttentionMetricsSnapshot,
    AttentionMode,
    Candidate,
    SalienceVector,
    ScoredCandidate,
    WorkingMemoryPort,
)
from .engine import AttentionEngine
from .errors import (
    AttentionError,
    AttentionSecurityError,
    InvalidCandidateError,
    UnknownAttentionOperationError,
)
from .port import AttentionWMPort
from .salience import SalienceEngine, compose

__all__ = [
    "AttentionEngine",
    "AttentionWMPort",
    "SalienceEngine",
    "compose",
    "SalienceVector",
    "Candidate",
    "ScoredCandidate",
    "AttentionConfig",
    "AttendResult",
    "AttentionMode",
    "AttentionMetricsSnapshot",
    "AttentionHealthReport",
    "WorkingMemoryPort",
    # errors
    "AttentionError",
    "InvalidCandidateError",
    "AttentionSecurityError",
    "UnknownAttentionOperationError",
]
