"""Evidence collection, evaluation, weighting, and belief evaluation.

Reasoning acts only on *conscious* content (ReL12). The collector reads the
conscious focus from Working Memory (public read contract), resolves each
reference to its Cognitive-State object (via the State Manager), and parses the
opaque payloads into the reasoning ABI: assertions become :class:`Evidence`,
implications become :class:`Rule`, cause->effect edges become :class:`CausalLink`,
and source cases become :class:`Analogy`. Nothing is copied — every parsed item
keeps its source ``handle`` for traceability (item 24).
"""

from __future__ import annotations

from typing import Any, Sequence

from ...state import CognitiveStateManager, ObjectStatus, ObjectType, Region
from .contracts import Analogy, CausalLink, Evidence, Rule

# Cognitive-State object kinds whose payloads reasoning may read as premises.
_ASSERTION_TYPES = {
    ObjectType.BELIEF: "belief",
    ObjectType.EVIDENCE: "evidence",
    ObjectType.PERCEPT: "percept",
    ObjectType.ASSUMPTION: "assumption",
    ObjectType.CONSTRAINT: "constraint",
    ObjectType.USER_MODEL: "belief",
}


def _f(payload: Any, key: str, default: float) -> float:
    try:
        return float(payload.get(key, default))
    except (TypeError, ValueError):
        return default


class ConsciousContent:
    """The parsed, conscious working set for one reasoning episode (references only)."""

    __slots__ = ("evidence", "rules", "causes", "analogies")

    def __init__(
        self,
        evidence: list[Evidence],
        rules: list[Rule],
        causes: list[CausalLink],
        analogies: list[Analogy],
    ) -> None:
        self.evidence = evidence
        self.rules = rules
        self.causes = causes
        self.analogies = analogies


class EvidenceCollector:
    """Gathers conscious references from WM and resolves them to premises (Ch2 §5.6).

    It never reaches into WM internals; it consumes the public read contract and
    the State Manager's read API. It performs no inference.
    """

    def __init__(self, state: CognitiveStateManager, wm_read: Any) -> None:
        self._state = state
        self._wm = wm_read

    def conscious_targets(self, workspace: str | None, restrict: tuple[str, ...]) -> list[str]:
        """The handles of the objects currently conscious (WM focus), deterministically ordered."""
        targets: list[str] = []
        seen: set[str] = set()
        for slot in self._wm.read_focus(workspace):
            t = getattr(slot, "target", None)
            if t is not None and t not in seen:
                seen.add(t)
                targets.append(t)
        if restrict:
            allowed = set(restrict)
            targets = [t for t in targets if t in allowed]
        targets.sort()
        return targets

    def collect(self, workspace: str | None, restrict: tuple[str, ...]) -> ConsciousContent:
        evidence: list[Evidence] = []
        rules: list[Rule] = []
        causes: list[CausalLink] = []
        analogies: list[Analogy] = []
        for handle in self.conscious_targets(workspace, restrict):
            if not self._state.exists(handle):
                continue
            obj = self._state.get(handle)
            self._parse(obj, evidence, rules, causes, analogies)
        return ConsciousContent(evidence, rules, causes, analogies)

    def _parse(
        self,
        obj: Any,
        evidence: list[Evidence],
        rules: list[Rule],
        causes: list[CausalLink],
        analogies: list[Analogy],
    ) -> None:
        payload = obj.payload
        # Implications (rules) — usable regardless of the carrying object type.
        rule = payload.get("rule")
        if isinstance(rule, dict) and "then" in rule:
            rules.append(
                Rule(
                    handle=obj.handle,
                    antecedents=tuple(rule.get("if", ())),
                    consequent=str(rule["then"]),
                    consequent_negated=bool(rule.get("negated", False)),
                    reliability=_f(rule, "reliability", 1.0),
                )
            )
        # Causal edges.
        causal = payload.get("causes")
        if isinstance(causal, dict) and "cause" in causal and "effect" in causal:
            causes.append(
                CausalLink(
                    handle=obj.handle,
                    cause=str(causal["cause"]),
                    effect=str(causal["effect"]),
                    strength=_f(causal, "strength", 1.0),
                )
            )
        # Analogical source case.
        analogy = payload.get("analogy")
        if isinstance(analogy, dict) and "relation" in analogy and "conclusion" in analogy:
            analogies.append(
                Analogy(
                    handle=obj.handle,
                    relation=str(analogy["relation"]),
                    conclusion=str(analogy["conclusion"]),
                    conclusion_negated=bool(analogy.get("negated", False)),
                    strength=_f(analogy, "strength", 1.0),
                )
            )
        # Plain assertion (a proposition the object asserts).
        statement = payload.get("statement")
        if statement is not None:
            kind = _ASSERTION_TYPES.get(obj.type, "belief")
            conf = obj.confidence if obj.confidence is not None else _f(payload, "confidence", 1.0)
            evidence.append(
                Evidence(
                    handle=obj.handle,
                    statement=str(statement),
                    negated=bool(payload.get("negated", False)),
                    reliability=_f(payload, "reliability", 1.0),
                    confidence=float(conf),
                    kind=kind,
                )
            )


class EvidenceEvaluator:
    """Evaluates and *weights* evidence (items 3, 4) and evaluates beliefs (item 7).

    Weight is a deterministic product of source reliability, asserted confidence,
    and goal relevance. Relevance is structural: evidence bearing on the question
    or on a rule/causal antecedent in play is more relevant than incidental content.
    """

    def weigh(
        self,
        evidence: Sequence[Evidence],
        *,
        question: str,
        relevant_statements: frozenset[str],
    ) -> list[Evidence]:
        out: list[Evidence] = []
        for e in evidence:
            relevance = 1.0 if (e.statement == question or e.statement in relevant_statements) else 0.6
            weight = max(0.0, min(1.0, e.reliability)) * max(0.0, min(1.0, e.confidence)) * relevance
            out.append(
                Evidence(
                    handle=e.handle, statement=e.statement, negated=e.negated,
                    reliability=e.reliability, confidence=e.confidence, kind=e.kind,
                    weight=round(weight, 6),
                )
            )
        out.sort(key=lambda x: (-x.weight, x.handle))
        return out

    def evaluate_belief(self, statement: str, evidence: Sequence[Evidence]) -> tuple[float, float]:
        """Return (support, opposition) net weight for a statement across the evidence.

        Belief evaluation (item 7): how strongly does the conscious evidence bear
        for and against a proposition? Combined by bounded noisy-OR (not naive sum).
        """
        support = _noisy_or([e.weight for e in evidence if e.statement == statement and not e.negated])
        oppose = _noisy_or([e.weight for e in evidence if e.statement == statement and e.negated])
        return support, oppose


def _noisy_or(weights: Sequence[float]) -> float:
    survive = 1.0
    for w in weights:
        survive *= 1.0 - max(0.0, min(1.0, w))
    return 1.0 - survive
