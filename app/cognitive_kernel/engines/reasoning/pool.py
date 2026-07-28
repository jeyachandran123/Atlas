"""The Reasoning Engine Port + Engine Pool — the model-independence boundary (ReL1).

Reasoning is a *faculty above substitutable engines*; no engine is "the reasoner".
This module ships three deterministic, pure-stdlib engines behind the port — a
**symbolic** engine (exact deduction & constraint checking), a **probabilistic**
engine (evidence weighing & induction), and a fast **heuristic** engine (System-1).
The Generation Platform (an LLM) would be *one more engine behind this same port*;
the faculty never depends on any engine's internals (P1/P6). The pool routes a
step to the right engine, supports ensembles, and *degrades gracefully* on engine
failure (ReL14) — it falls back, it never crashes.

Also here: the null Prediction port. Reasoning never predicts; it *requests*
forecasts through this hook (item 34). Until a Prediction engine exists, the null
port reports unavailable and reasoning proceeds without it (graceful degradation).
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .contracts import (
    EngineProduct,
    EngineRequest,
    ReasoningStep,
    ReasoningStrategy,
    ReasoningType,
)
from .inference import Derivation, abduce, causal_query, induce, prove, satisfy_constraints
from .evidence import _noisy_or


def _steps_from(derivs: Sequence[Derivation], engine: str) -> tuple[ReasoningStep, ...]:
    return tuple(
        ReasoningStep(
            index=i, rtype=ReasoningType.DEDUCTIVE, strategy=ReasoningStrategy.LINEAR, engine=engine,
            premises=d.premises, product=(("¬" if d.negated else "") + d.statement),
            confidence=d.confidence, rationale=d.note, depth=d.depth,
        )
        for i, d in enumerate(derivs)
    )


class SymbolicReasoningEngine:
    """Exact, verifiable deduction and constraint checking (GOFAI behind the port)."""

    name = "symbolic"
    handles = frozenset({ReasoningType.DEDUCTIVE, ReasoningType.CONSTRAINT})

    def propose(self, request: EngineRequest, context: Any) -> EngineProduct | None:
        if request.rtype is ReasoningType.CONSTRAINT:
            ok, violations = satisfy_constraints(request.facts, request.rules)
            return EngineProduct(
                engine=self.name, statement="constraints_satisfied" if ok else "constraint_violation",
                negated=not ok, confidence=1.0,
                justification="no forbidden combination asserted" if ok else f"violated: {list(violations)}",
                rtype=ReasoningType.CONSTRAINT, premises=violations,
            )
        if not request.question:
            return None  # symbolic deduction needs a goal to prove
        proof = prove(
            request.question, request.question_negated, request.facts, request.negations,
            request.rules, request.max_depth,
        )
        if not proof.proven:
            return None  # cannot derive -> let another engine try (graceful)
        return EngineProduct(
            engine=self.name, statement=request.question, negated=request.question_negated,
            confidence=proof.confidence, justification="derived by modus ponens",
            rtype=ReasoningType.DEDUCTIVE,
            premises=tuple(sorted({p for d in proof.derivations for p in d.premises})),
            steps=_steps_from(proof.derivations, self.name),
        )


class ProbabilisticReasoningEngine:
    """Weighs uncertain evidence (abduction/probabilistic) and generalises (induction)."""

    name = "probabilistic"
    handles = frozenset(
        {ReasoningType.ABDUCTIVE, ReasoningType.PROBABILISTIC, ReasoningType.DIAGNOSTIC,
         ReasoningType.INDUCTIVE, ReasoningType.CAUSAL}
    )

    def propose(self, request: EngineRequest, context: Any) -> EngineProduct | None:
        if request.rtype is ReasoningType.INDUCTIVE:
            gens = induce([e.statement for e in request.evidence if not e.negated])
            if not gens:
                return None
            g = gens[0]
            return EngineProduct(
                engine=self.name, statement=f"*.{g.predicate}", negated=False, confidence=g.confidence,
                justification=f"generalised from {g.count} instances", rtype=ReasoningType.INDUCTIVE,
                premises=g.instances,
            )
        if request.rtype is ReasoningType.CAUSAL and request.question:
            parents = causal_query(request.question, request.causes, direction="causes")
            if not parents:
                return None
            return EngineProduct(
                engine=self.name, statement=parents[0], negated=False, confidence=0.7,
                justification=f"causal antecedent of {request.question}", rtype=ReasoningType.CAUSAL,
                premises=tuple(parents),
            )
        # Abductive / probabilistic weighing of the ranked hypotheses.
        best: tuple[float, Any] | None = None
        for h in request.hypotheses:
            support = [e.weight for e in request.evidence if e.statement == h.statement and e.negated == h.negated]
            oppose = [e.weight for e in request.evidence if e.statement == h.statement and e.negated != h.negated]
            score = _noisy_or([h.prior, *support]) * (1.0 - _noisy_or(oppose))
            if best is None or score > best[0] or (score == best[0] and h.statement < best[1].statement):
                best = (score, h)
        if best is None:
            return None
        score, h = best
        return EngineProduct(
            engine=self.name, statement=h.statement, negated=h.negated, confidence=round(min(1.0, score), 6),
            justification="best-supported hypothesis by evidence weighing", hypothesis_id=h.hid,
            rtype=ReasoningType.ABDUCTIVE, premises=h.supports,
        )


class HeuristicReasoningEngine:
    """A single calibrated System-1 shortcut: the most a-priori-plausible hypothesis."""

    name = "heuristic"
    handles = frozenset(
        {ReasoningType.ABDUCTIVE, ReasoningType.DIAGNOSTIC, ReasoningType.STRATEGIC,
         ReasoningType.PROBABILISTIC}
    )

    def propose(self, request: EngineRequest, context: Any) -> EngineProduct | None:
        if not request.hypotheses:
            return None
        top = max(request.hypotheses, key=lambda h: (h.prior, -len(h.statement), h.statement))
        return EngineProduct(
            engine=self.name, statement=top.statement, negated=top.negated, confidence=top.prior,
            justification="fast heuristic (highest prior plausibility)", hypothesis_id=top.hid,
            rtype=request.rtype, premises=top.supports,
        )


# Preference order per type: exact/verifiable first, fast heuristic last (fallback).
_PREFERENCE: dict[ReasoningType, tuple[str, ...]] = {
    ReasoningType.DEDUCTIVE: ("symbolic",),
    ReasoningType.CONSTRAINT: ("symbolic",),
    ReasoningType.ABDUCTIVE: ("probabilistic", "heuristic"),
    ReasoningType.DIAGNOSTIC: ("probabilistic", "heuristic"),
    ReasoningType.PROBABILISTIC: ("probabilistic", "heuristic"),
    ReasoningType.INDUCTIVE: ("probabilistic",),
    ReasoningType.CAUSAL: ("probabilistic",),
    ReasoningType.STRATEGIC: ("heuristic",),
}


class EnginePool:
    """Routes a reasoning step to a substitutable engine; supports ensembles and
    graceful fallback (ReL14). Deterministic ordering by the preference table."""

    def __init__(self) -> None:
        self._engines: dict[str, Any] = {}

    def register(self, engine: Any) -> None:
        self._engines[engine.name] = engine

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._engines))

    def count(self) -> int:
        return len(self._engines)

    def _ordered(self, rtype: ReasoningType) -> list[Any]:
        preferred = _PREFERENCE.get(rtype, ())
        ordered = [self._engines[n] for n in preferred if n in self._engines]
        # Any other engine that declares it can handle the type (deterministic by name).
        for name in sorted(self._engines):
            eng = self._engines[name]
            if rtype in eng.handles and eng not in ordered:
                ordered.append(eng)
        return ordered

    def propose(self, request: EngineRequest, context: Any) -> EngineProduct | None:
        """First applicable engine that yields a product (falls back on failure)."""
        for engine in self._ordered(request.rtype):
            try:
                product = engine.propose(request, context)
            except Exception:  # ReL14: an engine failure is degraded, never propagated
                continue
            if product is not None:
                return product
        return None

    def ensemble(self, request: EngineRequest, context: Any, k: int) -> list[EngineProduct]:
        """Run up to ``k`` engines on one step; the faculty reconciles the products."""
        products: list[EngineProduct] = []
        for engine in self._ordered(request.rtype):
            if len(products) >= max(1, k):
                break
            try:
                product = engine.propose(request, context)
            except Exception:
                continue
            if product is not None:
                products.append(product)
        return products

    def verify(self, statement: str, negated: bool, request: EngineRequest, context: Any) -> bool:
        """Verify a candidate by attempting an independent symbolic proof (verify-then-trust)."""
        sym = self._engines.get("symbolic")
        if sym is None:
            return False
        proof = prove(statement, negated, request.facts, request.negations, request.rules, request.max_depth)
        return proof.proven


class NullPredictionPort:
    """Default Prediction hook: no Prediction engine is wired yet (item 34).

    Reasoning requests forecasts here and proceeds without them when unavailable —
    it never fabricates a prediction of its own (that is Prediction's authority)."""

    def available(self) -> bool:
        return False

    def request(self, scenario: Mapping[str, Any], context: Any) -> Mapping[str, Any] | None:
        return None


def default_pool() -> EnginePool:
    pool = EnginePool()
    pool.register(SymbolicReasoningEngine())
    pool.register(ProbabilisticReasoningEngine())
    pool.register(HeuristicReasoningEngine())
    return pool
