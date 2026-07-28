"""The Working Reasoning Space — transient, bounded, reconstructable scratch.

The episode's mental-model workspace (Phase 4, Ch2 §6): partial inferences, the
live hypothesis set, asserted facts, and the source references drawn in. It is
**reasoning-local and transient** — never a durable store (ReL2) and never a
Working-Memory workspace (Reasoning owns no WM). It holds *references* only (OL7),
is bounded (pruned like WM), and is fully serialisable so an interrupted episode
can be checkpointed and reconstructed from its trace + goal (ReL8, §4.3).
"""

from __future__ import annotations

import dataclasses
from typing import Any, Sequence

from .contracts import Evidence, Hypothesis, ReasoningStep


class WorkingReasoningSpace:
    __slots__ = (
        "episode_id", "goal", "_max_items", "facts", "negations",
        "hypotheses", "steps", "references",
    )

    def __init__(self, episode_id: str, goal: str, max_items: int = 128) -> None:
        self.episode_id = episode_id
        self.goal = goal
        self._max_items = max_items
        self.facts: dict[str, float] = {}          # statement -> confidence (positive)
        self.negations: dict[str, float] = {}      # statement -> confidence (negated)
        self.hypotheses: list[Hypothesis] = []
        self.steps: list[ReasoningStep] = []
        self.references: set[str] = set()          # source object handles (references, not copies)

    # --- seeding & assertion -------------------------------------------- #

    def seed(self, evidence: Sequence[Evidence]) -> None:
        for e in evidence:
            self.references.add(e.handle)
            self.assert_fact(e.statement, e.negated, e.confidence)

    def assert_fact(self, statement: str, negated: bool, confidence: float) -> None:
        table = self.negations if negated else self.facts
        table[statement] = max(table.get(statement, 0.0), round(confidence, 6))
        self._prune()

    def confidence_of(self, statement: str) -> float | None:
        if statement in self.facts:
            return self.facts[statement]
        if statement in self.negations:
            return self.negations[statement]
        return None

    # --- hypotheses ------------------------------------------------------ #

    def add_hypothesis(self, h: Hypothesis) -> None:
        self.hypotheses.append(h)
        self._prune()

    def upsert_hypothesis(
        self, *, statement: str, negated: bool, confidence: float,
        hid: str | None, derivation: str, supports: tuple[str, ...] = (),
    ) -> None:
        for i, h in enumerate(self.hypotheses):
            if h.statement == statement and h.negated == negated:
                self.hypotheses[i] = dataclasses.replace(
                    h, confidence=round(confidence, 6), derivation=derivation,
                    supports=supports or h.supports,
                )
                return
        self.hypotheses.append(
            Hypothesis(
                hid or f"h{len(self.hypotheses) + 1}", statement, negated,
                prior=round(confidence, 6), confidence=round(confidence, 6),
                supports=supports, derivation=derivation,
            )
        )
        self._prune()

    def top_hypothesis(self) -> Hypothesis | None:
        if not self.hypotheses:
            return None
        return max(self.hypotheses, key=lambda h: (h.confidence, h.statement, not h.negated))

    def runner_up(self) -> Hypothesis | None:
        ordered = sorted(self.hypotheses, key=lambda h: (-h.confidence, h.statement))
        return ordered[1] if len(ordered) >= 2 else None

    def top_confidence(self) -> float:
        top = self.top_hypothesis()
        return top.confidence if top else 0.0

    # --- trace ----------------------------------------------------------- #

    def add_step(self, step: ReasoningStep) -> None:
        self.steps.append(step)

    # --- bounded scratch (pruned like WM) -------------------------------- #

    def _prune(self) -> None:
        if len(self.hypotheses) > self._max_items:
            self.hypotheses.sort(key=lambda h: (-h.confidence, h.statement))
            del self.hypotheses[self._max_items:]

    # --- checkpoint / reconstruction (ReL8) ------------------------------ #

    def to_payload(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "goal": self.goal,
            "facts": dict(self.facts),
            "negations": dict(self.negations),
            "references": sorted(self.references),
            "hypotheses": [
                {
                    "hid": h.hid, "statement": h.statement, "negated": h.negated,
                    "prior": h.prior, "confidence": h.confidence, "supports": list(h.supports),
                    "derivation": h.derivation, "depth": h.depth,
                }
                for h in self.hypotheses
            ],
            "steps": [
                {
                    "index": s.index, "rtype": s.rtype.value, "strategy": s.strategy.value,
                    "engine": s.engine, "premises": list(s.premises), "product": s.product,
                    "confidence": s.confidence, "rationale": s.rationale, "depth": s.depth,
                }
                for s in self.steps
            ],
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "WorkingReasoningSpace":
        from .contracts import ReasoningStrategy, ReasoningType

        space = cls(payload["episode_id"], payload.get("goal", ""))
        space.facts = dict(payload.get("facts", {}))
        space.negations = dict(payload.get("negations", {}))
        space.references = set(payload.get("references", []))
        space.hypotheses = [
            Hypothesis(
                h["hid"], h["statement"], h["negated"], prior=h["prior"], confidence=h["confidence"],
                supports=tuple(h.get("supports", ())), derivation=h.get("derivation", "generated"),
                depth=h.get("depth", 0),
            )
            for h in payload.get("hypotheses", [])
        ]
        space.steps = [
            ReasoningStep(
                index=s["index"], rtype=ReasoningType(s["rtype"]), strategy=ReasoningStrategy(s["strategy"]),
                engine=s["engine"], premises=tuple(s.get("premises", ())), product=s["product"],
                confidence=s["confidence"], rationale=s.get("rationale", ""), depth=s.get("depth", 0),
            )
            for s in payload.get("steps", [])
        ]
        return space
