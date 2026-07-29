"""The Experience Collector — validated inputs to learning (LeL7, read-only).

Learning acts only on candidates that reached it through the *propose* pipeline
(LeL2). This collector gathers them from public contracts, read-only:

* ``LEARNING_CANDIDATE`` objects in **R9** (proposed by Reasoning) — the durable
  candidate stream;
* ``prediction.reconciled`` events (the ledger) — **realized** outcomes for
  calibration (never the hypothetical forecast — LeL7/LeL26);
* ``metacognition.finding`` events — Meta's recommendations (item 37), consumed as
  prioritisation signals, never as evidence.

It writes nothing and copies nothing durable — each experience keeps its source
handle (provenance anchor — LeL24).
"""

from __future__ import annotations

from typing import Any

from ...contracts import KernelServices
from ...state import CognitiveStateManager, ObjectStatus, ObjectType, Region
from .contracts import Experience, LearningKind


class CollectedExperience:
    __slots__ = ("candidates", "calibrations", "recommendations")

    def __init__(self, candidates, calibrations, recommendations) -> None:
        self.candidates: list[Experience] = candidates
        self.calibrations: list[Experience] = calibrations
        self.recommendations: list[dict] = recommendations


class ExperienceCollector:
    def __init__(self, services: KernelServices, state: CognitiveStateManager) -> None:
        self._services = services
        self._state = state

    def collect(self, since: int) -> CollectedExperience:
        return CollectedExperience(
            self._collect_candidates(), self._collect_reconciliations(since), self._collect_recommendations(since)
        )

    def _collect_candidates(self) -> list[Experience]:
        objs = self._state.query(region=Region.R9_METACOGNITIVE, type=ObjectType.LEARNING_CANDIDATE,
                                 status=ObjectStatus.PROPOSED)
        exps: list[Experience] = []
        for o in objs:
            p = o.payload
            statement = p.get("generalization") or p.get("statement")
            if not statement:
                continue
            try:
                kind = LearningKind(p["kind"]) if p.get("kind") else LearningKind.PATTERN_GENERALIZATION
            except ValueError:
                kind = LearningKind.PATTERN_GENERALIZATION
            exps.append(Experience(
                exp_id=o.handle, kind=kind, statement=str(statement),
                negated=bool(p.get("negated", False)), confidence=float(p.get("confidence", 0.5)),
                evidence_handle=o.handle, episode=str(p.get("episode", o.handle)), source="reasoning",
                seq=o.modified_seq,
            ))
        return sorted(exps, key=lambda e: (e.statement, e.episode))

    def _collect_reconciliations(self, since: int) -> list[Experience]:
        exps: list[Experience] = []
        for entry in self._services.ledger.read(since=since):
            ev = entry.event
            if ev.type == "prediction.reconciled":
                surprise = float(ev.payload.get("surprise", 0.0))
                exps.append(Experience(
                    exp_id=ev.event_id, kind=LearningKind.PREDICTION_RECONCILIATION, statement="prediction_calibration",
                    negated=False, confidence=max(0.0, 1.0 - surprise),
                    evidence_handle=str(ev.payload.get("request_id", "")),
                    episode=str(ev.payload.get("request_id", ev.event_id)), source="prediction", seq=ev.sequence,
                ))
        return exps

    def _collect_recommendations(self, since: int) -> list[dict]:
        recs: list[dict] = []
        for entry in self._services.ledger.read(since=since):
            ev = entry.event
            if ev.type == "metacognition.finding":
                recs.append({"kind": ev.payload.get("kind"), "subject": ev.payload.get("subject"),
                             "detail": ev.payload.get("detail")})
        return recs
