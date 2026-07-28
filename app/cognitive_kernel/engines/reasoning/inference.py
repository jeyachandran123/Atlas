"""The Logical Inference Engine — deterministic implementations of each type.

Pure functions over the reasoning ABI (no I/O, no engine coupling): deduction
(modus ponens, forward & backward, recursion-bounded — P8), induction,
abduction (inference to the best explanation — the default under uncertainty),
analogical transfer, causal query, and constraint satisfaction. Every derivation
obeys the monotonicity law (ReL4): a conclusion is no more confident than its
weakest necessary premise. Determinism is guaranteed by total, tie-broken
orderings throughout (ReL6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .contracts import Analogy, CausalLink, Rule

CONTRADICTION = "⊥"  # the falsum: a constraint rule concluding this marks a forbidden combination


@dataclass(frozen=True, slots=True)
class Derivation:
    statement: str
    negated: bool
    confidence: float
    premises: tuple[str, ...]
    rule_handle: str
    depth: int
    note: str


@dataclass(frozen=True, slots=True)
class Proof:
    proven: bool
    confidence: float
    derivations: tuple[Derivation, ...]


@dataclass(frozen=True, slots=True)
class ScoredExplanation:
    statement: str            # the candidate cause / explanation
    covered: tuple[str, ...]  # observations it explains
    score: float
    strength: float
    handles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Generalization:
    predicate: str
    count: int
    confidence: float
    instances: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Transfer:
    statement: str
    negated: bool
    confidence: float
    source: str


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


# --- deduction (item 9) ----------------------------------------------------- #


def prove(
    goal: str,
    negated: bool,
    facts: Mapping[str, float],
    negations: Mapping[str, float],
    rules: Sequence[Rule],
    max_depth: int,
    *,
    _seen: frozenset[tuple[str, bool]] | None = None,
    _depth: int = 0,
) -> Proof:
    """Backward-chaining proof of ``goal`` (recursive, cycle-guarded, depth-bounded).

    Recursion is the natural expression of *recursive reasoning* (item 22): to
    prove a goal, prove the antecedents of a rule that concludes it — bounded by
    ``max_depth`` so the mind never spins (P8).
    """
    table = negations if negated else facts
    if goal in table:
        return Proof(True, table[goal], (Derivation(goal, negated, table[goal], (), "", _depth, "asserted"),))
    if _depth >= max_depth:
        return Proof(False, 0.0, ())
    seen = _seen or frozenset()
    if (goal, negated) in seen:
        return Proof(False, 0.0, ())  # cycle guard
    seen = seen | {(goal, negated)}

    candidates = sorted(
        (r for r in rules if r.consequent == goal and r.consequent_negated == negated),
        key=lambda r: r.handle,
    )
    best: Proof | None = None
    for r in candidates:
        derivs: list[Derivation] = []
        confs: list[float] = [_clamp(r.reliability)]
        ok = True
        for a in r.antecedents:
            sub = prove(a, False, facts, negations, rules, max_depth, _seen=seen, _depth=_depth + 1)
            if not sub.proven:
                ok = False
                break
            derivs.extend(sub.derivations)
            confs.append(sub.confidence)
        if not ok:
            continue
        conf = min(confs)  # monotonicity (ReL4)
        derivs.append(Derivation(goal, negated, conf, r.antecedents, r.handle, _depth, "modus_ponens"))
        proof = Proof(True, conf, tuple(derivs))
        if best is None or proof.confidence > best.confidence:
            best = proof
    return best or Proof(False, 0.0, ())


def deduce_forward(facts: Mapping[str, float], rules: Sequence[Rule], max_iters: int) -> list[Derivation]:
    """Forward-chain to a fixpoint, deriving all necessary consequences (item 9)."""
    known = dict(facts)
    derived: list[Derivation] = []
    for _ in range(max(1, max_iters)):
        changed = False
        for r in sorted(rules, key=lambda r: r.handle):
            if r.consequent_negated or r.consequent == CONTRADICTION:
                continue
            if r.consequent in known:
                continue
            if all(a in known for a in r.antecedents):
                conf = min([known[a] for a in r.antecedents] + [_clamp(r.reliability)])
                known[r.consequent] = conf
                derived.append(Derivation(r.consequent, False, conf, r.antecedents, r.handle, 0, "modus_ponens"))
                changed = True
        if not changed:
            break
    return derived


# --- abduction (item 11) ---------------------------------------------------- #


def abduce(
    observations: frozenset[str],
    causes: Sequence[CausalLink],
    parsimony_penalty: float,
) -> list[ScoredExplanation]:
    """Inference to the best explanation: rank causes by how much they explain.

    Score = coverage (fraction of observations explained) x mean causal strength.
    Ties are broken lexicographically for determinism. The top result is the best
    explanation — the mind's default under incomplete information (Peirce).
    """
    buckets: dict[str, dict[str, list]] = {}
    for link in sorted(causes, key=lambda c: c.handle):
        if link.effect in observations:
            b = buckets.setdefault(link.cause, {"covered": set(), "strength": [], "handles": []})
            b["covered"].add(link.effect)
            b["strength"].append(_clamp(link.strength))
            b["handles"].append(link.handle)
    n = max(1, len(observations))
    scored: list[ScoredExplanation] = []
    for cause, b in buckets.items():
        coverage = len(b["covered"]) / n
        strength = sum(b["strength"]) / len(b["strength"])
        score = _clamp(coverage * strength)
        scored.append(
            ScoredExplanation(
                statement=cause, covered=tuple(sorted(b["covered"])), score=round(score, 6),
                strength=round(strength, 6), handles=tuple(sorted(b["handles"])),
            )
        )
    scored.sort(key=lambda s: (-s.score, s.statement))
    return scored


# --- induction (item 10) ---------------------------------------------------- #


def induce(statements: Sequence[str], min_instances: int = 2) -> list[Generalization]:
    """Generalise a rule from recurring instances (``subject.predicate`` form).

    Never certain (the problem of induction): confidence rises with the number of
    supporting instances but is always < 1 (confidence-qualified).
    """
    groups: dict[str, list[str]] = {}
    for s in statements:
        if "." in s:
            _, predicate = s.rsplit(".", 1)
            groups.setdefault(predicate, []).append(s)
    out: list[Generalization] = []
    for predicate, insts in sorted(groups.items()):
        n = len(insts)
        if n >= min_instances:
            out.append(
                Generalization(
                    predicate=predicate, count=n, confidence=round(1.0 - 1.0 / (n + 1), 6),
                    instances=tuple(sorted(insts)),
                )
            )
    out.sort(key=lambda g: (-g.confidence, g.predicate))
    return out


# --- analogical transfer (item 12) ------------------------------------------ #


def analogize(analogies: Sequence[Analogy], target_relation: str, discount: float = 0.8) -> list[Transfer]:
    """Transfer a conclusion from a source case sharing the target relation.

    Discounted (superficial similarity misleads); confidence never exceeds the
    source strength times the analogical discount.
    """
    transfers = [
        Transfer(a.conclusion, a.conclusion_negated, round(_clamp(a.strength) * discount, 6), a.handle)
        for a in analogies
        if a.relation == target_relation
    ]
    transfers.sort(key=lambda t: (-t.confidence, t.source))
    return transfers


# --- causal query (item 13) ------------------------------------------------- #


def causal_query(statement: str, causes: Sequence[CausalLink], *, direction: str) -> list[str]:
    """Query the causal graph. ``direction='effects'`` -> children; else -> parents."""
    if direction == "effects":
        found = {c.effect for c in causes if c.cause == statement}
    else:
        found = {c.cause for c in causes if c.effect == statement}
    return sorted(found)


# --- constraint satisfaction (item 14) -------------------------------------- #


def satisfy_constraints(facts: Mapping[str, float], rules: Sequence[Rule]) -> tuple[bool, tuple[str, ...]]:
    """Check the current facts against constraint rules (consequent = falsum).

    Returns ``(satisfied, violated_rule_handles)``. A violation means a forbidden
    combination of facts is simultaneously asserted.
    """
    violations = [
        r.handle
        for r in sorted(rules, key=lambda r: r.handle)
        if r.consequent == CONTRADICTION and r.antecedents and all(a in facts for a in r.antecedents)
    ]
    return (len(violations) == 0, tuple(violations))
