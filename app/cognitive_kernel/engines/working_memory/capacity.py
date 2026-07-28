"""Capacity & eviction — bounded and deterministic (CL1/P3).

Eviction follows the constitutional research (Phase 2.5 §5.5): the lowest
effective-activation, unpinned reference is the victim. Ties break
deterministically by (activation, loaded_seq, handle) so replay/tests are
reproducible.
"""

from __future__ import annotations

from .contracts import Slot


def select_eviction_victim(slots: list[Slot], now: int, decay_rate: float) -> Slot | None:
    """Return the lowest-activation unpinned slot, or ``None`` if all are pinned."""
    candidates = [s for s in slots if not s.pinned]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda s: (s.effective_activation(now, decay_rate), s.loaded_seq, s.handle),
    )
