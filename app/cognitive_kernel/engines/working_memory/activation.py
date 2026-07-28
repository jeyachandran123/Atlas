"""Activation dynamics — deterministic, ephemeral decay (Phase 2.5 §5.6).

Activation is NOT stored per step (that would bloat versioned state); it is a
pure function of the reference's base activation and the elapsed logical time.
The manager materialises a value into state only on meaningful transitions
(load/refresh/evict).
"""

from __future__ import annotations

import math


def effective(base_activation: float, loaded_seq: int, now: int, decay_rate: float, pinned: bool) -> float:
    if pinned:
        return max(base_activation, 1.0)
    dt = max(0, now - loaded_seq)
    return base_activation * math.exp(-decay_rate * dt)


def refreshed_activation(current_effective: float, boost: float) -> float:
    """A refresh boosts the reference and resets its decay clock (§5.6)."""
    return min(1.0, current_effective + boost)
