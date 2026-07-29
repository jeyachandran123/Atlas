"""Cognitive State access for Development — **read-only** (DeL13).

Development produces proposals only; it writes no Cognitive State. This module holds
the canonical-protection watermark so a development cycle can *prove* it changed
nothing (development artifacts live in the engine repository and the Ledger).
"""

from __future__ import annotations

from ...state import CognitiveStateManager


def canonical_object_count(state: CognitiveStateManager) -> int:
    return len(state.all_current())
