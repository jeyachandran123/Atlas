"""Cognitive State access for Meta-Cognition — **read-only** (MeL9/MeL11/MeL13).

Meta reads Cognitive State only through the State Manager and **writes nothing** —
there is deliberately no write helper. Reflection artifacts live in the engine's own
immutable repository and the Ledger (audit), never in a canonical region. The
canonical object count is exposed so reflection can *prove* it changed nothing.
"""

from __future__ import annotations

from ...state import CognitiveStateManager


def canonical_object_count(state: CognitiveStateManager) -> int:
    """Total current objects across every region — the protection watermark."""
    return len(state.all_current())
