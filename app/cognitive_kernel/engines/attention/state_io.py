"""Cognitive State R3 I/O — the durable attention record.

Attention's Focus, Salience map, and Inhibition set are R3 objects (Phase 1 §R3),
written atomically through the Cognitive State Manager. Their version history is
the attention history (OL4/AL26). Attention keeps no durable state of its own.
"""

from __future__ import annotations

from typing import Any, Mapping

from ...state import CognitiveStateManager, ObjectStatus, ObjectType, Region

_TYPES = (ObjectType.ATTENTION_FOCUS, ObjectType.SALIENCE, ObjectType.INHIBITION)


def read_state(state: CognitiveStateManager) -> dict[ObjectType, Any]:
    out: dict[ObjectType, Any] = {}
    for t in _TYPES:
        q = state.query(region=Region.R3_ATTENTION, type=t, status=ObjectStatus.ACTIVE)
        if q:
            out[t] = q[0]
    return out


def write_state(
    state: CognitiveStateManager,
    context: Any,
    *,
    focus: Mapping[str, Any],
    salience: Mapping[str, Any],
    inhibition: Mapping[str, Any],
) -> dict[ObjectType, str]:
    """Upsert the three R3 attention objects in one atomic transaction (RL3)."""
    existing = {t: obj.handle for t, obj in read_state(state).items()}
    tx = state.begin_transaction(context)
    handles: dict[ObjectType, str] = {}
    for otype, payload in (
        (ObjectType.ATTENTION_FOCUS, focus),
        (ObjectType.SALIENCE, salience),
        (ObjectType.INHIBITION, inhibition),
    ):
        if otype in existing:
            tx.update(existing[otype], payload_replace=dict(payload))
            handles[otype] = existing[otype]
        else:
            handles[otype] = tx.create(otype, payload=dict(payload))
    tx.commit()
    return handles
