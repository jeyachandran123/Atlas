"""The Constitution Registry — read-only index of frozen law.

The eleven constitutional documents (Phases 0–9) are immutable. This registry is
their *runtime index*: every engine loads its constitutional rules from here, so
no engine duplicates constitutional text (single source of truth). The registry
is read-only, versioned, and validated; future constitutional upgrades bump the
version without any engine changing behaviour (engines reference law *codes*).

The authoritative full text lives in ``docs/architecture/*.md``. This registry
holds the canonical code, phase, title, and a one-line statement per law, which
is what runtime checks and audits reference.
"""

from __future__ import annotations

from typing import Sequence

from .contracts import ConstitutionVersion, ConstitutionRegistry, Law
from .errors import ConstitutionViolation

# The frozen phases (immutable).
PHASES: tuple[str, ...] = (
    "Phase 0 — Cognitive Philosophy",
    "Phase 1 — Cognitive State",
    "Phase 1.5 — Cognitive Object Model",
    "Phase 2 — Cognitive Runtime",
    "Phase 2.5 — Global Workspace",
    "Phase 3 — Attention",
    "Phase 4 — Reasoning",
    "Phase 5 — Executive Cognition",
    "Phase 6 — Predictive Cognition",
    "Phase 7 — Meta-Cognition",
    "Phase 8 — Adaptive Learning",
    "Phase 9 — Cognitive Development",
)

# Canonical law index. A curated, load-bearing subset per family; the registry
# is the single runtime source, full text in the frozen documents.
_LAWS: tuple[Law, ...] = (
    # Phase 0 — the twelve immutable principles.
    Law("P1", "Phase 0", "Mind ≠ Faculties", "The mind orchestrates faculties through interfaces; it never re-implements one."),
    Law("P2", "Phase 0", "State is first-class & persistent", "Every episode reads and writes durable cognitive state."),
    Law("P3", "Phase 0", "Bounded working memory", "Active reasoning operates over a strictly capacity-limited workspace."),
    Law("P4", "Phase 0", "Observed & reversible", "Every cognitive act is recorded; world-effects are reversible-by-design."),
    Law("P5", "Phase 0", "Proportional deliberation", "Cognitive effort scales with stakes and uncertainty."),
    Law("P6", "Phase 0", "Interfaces over implementations", "Every component is behind a contract and independently replaceable."),
    Law("P7", "Phase 0", "Explicit, durable goals", "Behavior is goal-directed; the intentional state is inspectable."),
    Law("P8", "Phase 0", "Metacognition can preempt", "The supervisor may halt, redirect, throttle, or escalate any process."),
    Law("P9", "Phase 0", "Learning must not corrupt", "Learned change is versioned, validated, reversible, and gated."),
    Law("P10", "Phase 0", "Human-in-the-loop", "Escalation, approval, and correction are first-class control paths."),
    Law("P11", "Phase 0", "Modality-agnostic cognition", "The core operates on abstract percepts and capabilities."),
    Law("P12", "Phase 0", "No hidden state", "All durable cognitive state lives in the state store / ledger."),
    # Phase 1.5 — object laws (selected).
    Law("OL1", "Phase 1.5", "Single responsibility", "Each cognitive object answers exactly one question."),
    Law("OL4", "Phase 1.5", "Versioned", "Every mutation produces a new version; history is never lost."),
    Law("OL6", "Phase 1.5", "Auditable", "Every version traces to the events that produced it."),
    Law("OL7", "Phase 1.5", "Relationship over duplication", "Objects reference; they never copy each other's content."),
    Law("OL8", "Phase 1.5", "Implementation-independent", "Objects are defined by responsibility, not storage or language."),
    # Phase 2 — runtime laws (selected).
    Law("RL1", "Phase 2", "Cognition is continuous", "The loop never halts; silence is low-power cognition."),
    Law("RL3", "Phase 2", "Transactional transitions", "Every state transition is a committed transaction; no partial minds."),
    Law("RL4", "Phase 2", "Logical time is authoritative", "Order, causality, replay, checkpoints are defined by logical time."),
    Law("RL6", "Phase 2", "Technology independence", "Mechanisms are defined by cognitive role, not by any vendor."),
    Law("RL8", "Phase 2", "Replayability", "Given the event stream, any state is deterministically reconstructable."),
    # Phase 2.5 — consciousness laws (selected).
    Law("CL1", "Phase 2.5", "Consciousness is bounded", "The conscious field holds only a few chunks."),
    Law("CL7", "Phase 2.5", "Broadcast never duplicates", "Broadcast disseminates references, not copies."),
    # Phase 3 — attention laws (selected).
    Law("AL2", "Phase 3", "Attention is explainable", "Salience is a retained vector with a 'because'."),
    Law("AL17", "Phase 3", "Attention is model-independent", "What is 'salient' does not change when the engine changes."),
    # Phase 4 — reasoning laws (selected).
    Law("ReL1", "Phase 4", "Faculty above engines", "Reasoning governs substitutable engines; no engine is 'the reasoner'."),
    Law("ReL9", "Phase 4", "Propose, not commit", "Reasoning/reflection propose; they never commit durable change."),
    # Phase 5 — executive laws (selected).
    Law("ExL1", "Phase 5", "Sole authorizer", "Only the executive may authorize cognition and world-action."),
    Law("ExL7", "Phase 5", "Cannot bypass safety", "Executive authority cannot override safety constraints."),
    Law("ExL12", "Phase 5", "Governs within identity", "The executive may not overwrite the identity Core."),
    # Phase 6 — predictive laws (selected).
    Law("PrL8", "Phase 6", "Simulation never mutates reality", "Simulation runs on isolated branches only."),
    Law("PrL9", "Phase 6", "Imagined content never becomes belief", "Simulated content is quarantined from memory."),
    # Phase 7 — meta-cognition laws (selected).
    Law("MeL6", "Phase 7", "Halt, not authorize", "Meta may halt/flag/propose; it may never start/commit/authorize."),
    Law("MeL12", "Phase 7", "Cannot alter the constitution", "Meta operates within the frozen laws."),
    Law("MeL16", "Phase 7", "Grounded, not confabulated", "The self-model is grounded in observed traces, not introspection."),
    # Phase 8 — learning laws (selected).
    Law("LeL5", "Phase 8", "Cannot alter the constitution", "Learning evolves content within the fixed structure only."),
    Law("LeL7", "Phase 8", "Validated experience only", "Learning is from validated experience, never raw interaction."),
    Law("LeL13", "Phase 8", "Every learning is reversible", "Every commit is versioned with a defined rollback."),
    # Phase 9 — development laws (selected).
    Law("DeL1", "Phase 9", "Identity invariant to development", "A matured mind is the same mind under the same laws."),
    Law("DeL3", "Phase 9", "Autonomy requires human approval", "The mind cannot grant itself autonomy."),
    Law("DeL8", "Phase 9", "Human authority undiminished", "Maturity never reduces ultimate human oversight."),
)

_VERSION = ConstitutionVersion(version="1.0.0", frozen_at="2026-07-27", law_count=len(_LAWS))


class FrozenConstitution(ConstitutionRegistry):
    """A read-only registry. There is deliberately no mutation API."""

    def __init__(self, laws: Sequence[Law] = _LAWS, version: ConstitutionVersion = _VERSION) -> None:
        # Build an immutable index once; validate uniqueness of codes.
        index: dict[str, Law] = {}
        for law in laws:
            if law.code in index:
                raise ConstitutionViolation(f"Duplicate law code: {law.code}")
            index[law.code] = law
        self._index = index
        self._laws = tuple(laws)
        self._version = version

    def version(self) -> ConstitutionVersion:
        return self._version

    def laws(self, *, phase: str | None = None) -> Sequence[Law]:
        if phase is None:
            return self._laws
        return tuple(law for law in self._laws if law.phase == phase)

    def law(self, code: str) -> Law:
        try:
            return self._index[code]
        except KeyError as exc:
            raise ConstitutionViolation(f"Unknown law code: {code}") from exc

    def has(self, code: str) -> bool:
        return code in self._index
