"""The Conflict Resolver (Phase 5 Ch6) — the mind's conflict monitor.

Conflict monitoring *recruits* executive control (Botvinick). This resolver
detects, classifies, and resolves cross-cutting conflicts by the fixed, auditable
ladder (ExL23): **Safety/Identity (absolute) → Priority → Confidence → Authority →
Compromise → Override → Escalate**. Safety and Identity dominate lexicographically
(ExL7/ExL12); nothing is ever resolved by silent last-write-wins.
"""

from __future__ import annotations

import uuid
from typing import Mapping, Sequence

from .contracts import Conflict, ConflictType, ExecutiveConfig, ResolutionBasis


class ConflictResolver:
    def __init__(self, config: ExecutiveConfig) -> None:
        self._config = config
        self._margin = 0.1  # material-difference threshold for priority/confidence/authority

    def resolve(
        self,
        ctype: ConflictType,
        parties: Sequence[str],
        *,
        safety: bool = False,
        identity: bool = False,
        safe_party: str | None = None,
        priorities: Mapping[str, float] | None = None,
        confidences: Mapping[str, float] | None = None,
        authorities: Mapping[str, float] | None = None,
        compromise_possible: bool = False,
        override_party: str | None = None,
    ) -> Conflict:
        cid = "conflict-" + uuid.uuid4().hex
        parties = tuple(parties)

        # 1-2. Safety / Identity — absolute (ExL7/ExL12).
        if safety:
            return self._done(cid, ConflictType.SAFETY, parties, ResolutionBasis.SAFETY,
                              safe_party or (parties[0] if parties else None), "safety dominates absolutely")
        if identity:
            return self._done(cid, ConflictType.IDENTITY, parties, ResolutionBasis.IDENTITY,
                              safe_party or (parties[0] if parties else None), "identity-core dominates absolutely")

        # 3. Priority.
        winner = self._clear_winner(priorities)
        if winner is not None:
            return self._done(cid, ctype, parties, ResolutionBasis.PRIORITY, winner, "higher priority wins")

        # 4. Confidence (calibration-weighted).
        winner = self._clear_winner(confidences)
        if winner is not None:
            return self._done(cid, ctype, parties, ResolutionBasis.CONFIDENCE, winner, "higher confidence wins")

        # 5. Authority.
        winner = self._clear_winner(authorities)
        if winner is not None:
            return self._done(cid, ctype, parties, ResolutionBasis.AUTHORITY, winner, "legitimate authority wins")

        # 6. Compromise.
        if compromise_possible:
            return self._done(cid, ctype, parties, ResolutionBasis.COMPROMISE, None, "re-scoped so both partially satisfied")

        # 7. Override (audited).
        if override_party is not None:
            return self._done(cid, ctype, parties, ResolutionBasis.OVERRIDE, override_party, "executive override (audited)")

        # 8. Escalate to human (P10).
        return Conflict(cid, ctype, parties, ResolutionBasis.ESCALATE, None, resolved=False, escalated=True,
                        detail="contested / balanced — escalated to human")

    def _clear_winner(self, values: Mapping[str, float] | None) -> str | None:
        if not values or len(values) < 2:
            return None
        ordered = sorted(values.items(), key=lambda kv: (-kv[1], kv[0]))
        if ordered[0][1] - ordered[1][1] >= self._margin:
            return ordered[0][0]
        return None

    def _done(self, cid, ctype, parties, basis, winner, detail) -> Conflict:
        return Conflict(cid, ctype, parties, basis, winner, resolved=True, escalated=False, detail=detail)
