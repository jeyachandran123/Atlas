"""Cognitive State access for Prediction — **read-only** (PrL8, canonical protection).

Prediction reads Cognitive State only through the State Manager and **writes
nothing** — there is deliberately no write helper in this module. The canonical
object count is exposed so the engine (and the architecture tests) can *prove* that
a forecast leaves canonical state untouched (item 37). Audit/retention of forecasts
goes to the Ledger and the engine's in-memory history — never to a State region.
"""

from __future__ import annotations

from typing import Any, Sequence

from ...state import CognitiveStateManager, Region


def canonical_object_count(state: CognitiveStateManager) -> int:
    """Total current objects across every region — the protection watermark (item 37)."""
    return len(state.all_current())


def region_counts(state: CognitiveStateManager) -> dict[str, int]:
    counts: dict[str, int] = {}
    for obj in state.all_current():
        counts[obj.region.value] = counts.get(obj.region.value, 0) + 1
    return counts


def read_objects(state: CognitiveStateManager, handles: Sequence[str]) -> list[Any]:
    """Fetch canonical objects read-only (references resolved, never copied durably)."""
    return [state.get(h) for h in handles if state.exists(h)]
