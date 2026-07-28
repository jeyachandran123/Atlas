"""Biased competition, winner selection, and focus-coalition construction.

Deterministic (AL10): eliminate the dominated, sort by (composite desc, handle),
threshold at ignition, cap at coalition capacity. May ignite nothing (AL11).
Interrupt candidates (surprise/safety) preempt (Phase 2.5 Ch10).
"""

from __future__ import annotations

from .contracts import AttentionConfig, ScoredCandidate


def is_interrupt(sc: ScoredCandidate, config: AttentionConfig) -> bool:
    return (
        sc.vector.safety_implications >= config.safety_veto
        or sc.vector.surprise >= config.interrupt_threshold
    )


def compete(
    scored: list[ScoredCandidate],
    config: AttentionConfig,
    *,
    fatigue: float = 0.0,
) -> tuple[list[ScoredCandidate], list[str]]:
    """Return (winners forming the coalition, inhibited targets).

    Fatigue raises the effective ignition threshold (vigilance decrement, AL14).
    """
    # Elimination round: drop the clearly-dominated.
    survivors = [s for s in scored if s.composite >= config.elimination_floor]
    # Deterministic ordering.
    survivors.sort(key=lambda s: (-s.composite, s.target))

    # Interrupts always enter (preemption), even under fatigue.
    interrupts = [s for s in survivors if is_interrupt(s, config)]
    threshold = min(1.0, config.ignition_threshold + fatigue)

    winners: list[ScoredCandidate] = []
    chosen: set[str] = set()
    for s in interrupts:
        if len(winners) >= config.coalition_capacity:
            break
        winners.append(s)
        chosen.add(s.target)

    for s in survivors:
        if s.target in chosen:
            continue
        if len(winners) >= config.coalition_capacity:
            break
        if s.composite < threshold:
            break  # below ignition -> stop (AL11: ignite nothing more)
        winners.append(s)
        chosen.add(s.target)

    inhibited = [s.target for s in survivors if s.target not in chosen]
    return winners, inhibited
