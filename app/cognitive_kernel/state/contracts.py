"""The Cognitive State ABI — enums, value objects, and Protocols.

Faithful to Phase 1 (ten Regions), Phase 1.5 (object substrate + eleven
relationship types), and Phase 2.5 (references, not copies). The manager treats
each object's ``payload`` as OPAQUE data — it owns structure, versioning, and
integrity; engines own meaning.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class Region(enum.Enum):
    """The ten Regions of the Cognitive State (Phase 1, Ch2)."""

    R1_IDENTITY = "R1"
    R2_INTENTIONAL = "R2"
    R3_ATTENTION = "R3"
    R4_WORKING_MEMORY = "R4"
    R5_BELIEF = "R5"
    R6_DELIBERATIVE = "R6"
    R7_PREDICTIVE = "R7"
    R8_TEMPORAL = "R8"
    R9_METACOGNITIVE = "R9"
    R10_ENVIRONMENTAL = "R10"


class ObjectType(enum.Enum):
    """Cognitive object kinds (Phase 1.5) and the region-fields they realise."""

    # R1 — Identity
    IDENTITY = "identity"
    ROLE = "role"
    PERSONA = "persona"
    CAPABILITY = "capability"
    # R2 — Intentional
    GOAL = "goal"
    INTENT = "intent"
    # R3 — Attention
    ATTENTION_FOCUS = "attention_focus"
    SALIENCE = "salience"
    INHIBITION = "inhibition"
    # R4 — Working-memory interface (references only)
    WORKING_MEMORY_REF = "working_memory_ref"
    ACTIVATED_KNOWLEDGE = "activated_knowledge"
    # R5 — Belief / world model
    BELIEF = "belief"
    ASSUMPTION = "assumption"
    CONSTRAINT = "constraint"
    USER_MODEL = "user_model"
    PERCEPT = "percept"
    EVIDENCE = "evidence"
    # R6 — Deliberative
    STRATEGY = "strategy"
    PLAN = "plan"
    TASK = "task"
    REASONING_STATE = "reasoning_state"
    # R7 — Predictive
    PREDICTION = "prediction"
    EXPECTATION = "expectation"
    # R8 — Temporal
    TEMPORAL_CONTEXT = "temporal_context"
    # R9 — Metacognitive
    REFLECTION = "reflection"
    LEARNING_CANDIDATE = "learning_candidate"
    EXECUTIVE_DECISION = "executive_decision"
    RISK = "risk"
    UNCERTAINTY = "uncertainty"
    # R10 — Environmental
    WORKSPACE_HANDLE = "workspace_handle"
    CONVERSATION_HANDLE = "conversation_handle"


class ObjectStatus(enum.Enum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"
    RETRACTED = "retracted"
    SUPERSEDED = "superseded"


class RelationshipType(enum.Enum):
    """The eleven relationship types (Phase 1.5, Ch11) + two associations."""

    OWNERSHIP = "ownership"
    COMPOSITION = "composition"
    AGGREGATION = "aggregation"
    ASSOCIATION = "association"
    DEPENDENCY = "dependency"
    INFLUENCE = "influence"
    ACTIVATION = "activation"
    INHERITANCE = "inheritance"
    CONTAINMENT = "containment"
    VERSION = "version"
    TEMPORAL = "temporal"
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"


# Relationship edge types that must form a DAG (no cycles).
DAG_EDGES: frozenset[RelationshipType] = frozenset(
    {
        RelationshipType.DEPENDENCY,
        RelationshipType.COMPOSITION,
        RelationshipType.VERSION,
        RelationshipType.TEMPORAL,
        RelationshipType.INHERITANCE,
    }
)

# Constitutional placement: each object type belongs in exactly one Region.
TYPE_REGION: dict[ObjectType, Region] = {
    ObjectType.IDENTITY: Region.R1_IDENTITY,
    ObjectType.ROLE: Region.R1_IDENTITY,
    ObjectType.PERSONA: Region.R1_IDENTITY,
    ObjectType.CAPABILITY: Region.R1_IDENTITY,
    ObjectType.GOAL: Region.R2_INTENTIONAL,
    ObjectType.INTENT: Region.R2_INTENTIONAL,
    ObjectType.ATTENTION_FOCUS: Region.R3_ATTENTION,
    ObjectType.SALIENCE: Region.R3_ATTENTION,
    ObjectType.INHIBITION: Region.R3_ATTENTION,
    ObjectType.WORKING_MEMORY_REF: Region.R4_WORKING_MEMORY,
    ObjectType.ACTIVATED_KNOWLEDGE: Region.R4_WORKING_MEMORY,
    ObjectType.BELIEF: Region.R5_BELIEF,
    ObjectType.ASSUMPTION: Region.R5_BELIEF,
    ObjectType.CONSTRAINT: Region.R5_BELIEF,
    ObjectType.USER_MODEL: Region.R5_BELIEF,
    ObjectType.PERCEPT: Region.R5_BELIEF,
    ObjectType.EVIDENCE: Region.R5_BELIEF,
    ObjectType.STRATEGY: Region.R6_DELIBERATIVE,
    ObjectType.PLAN: Region.R6_DELIBERATIVE,
    ObjectType.TASK: Region.R6_DELIBERATIVE,
    ObjectType.REASONING_STATE: Region.R6_DELIBERATIVE,
    ObjectType.PREDICTION: Region.R7_PREDICTIVE,
    ObjectType.EXPECTATION: Region.R7_PREDICTIVE,
    ObjectType.TEMPORAL_CONTEXT: Region.R8_TEMPORAL,
    ObjectType.REFLECTION: Region.R9_METACOGNITIVE,
    ObjectType.LEARNING_CANDIDATE: Region.R9_METACOGNITIVE,
    ObjectType.EXECUTIVE_DECISION: Region.R9_METACOGNITIVE,
    ObjectType.RISK: Region.R9_METACOGNITIVE,
    ObjectType.UNCERTAINTY: Region.R9_METACOGNITIVE,
    ObjectType.WORKSPACE_HANDLE: Region.R10_ENVIRONMENTAL,
    ObjectType.CONVERSATION_HANDLE: Region.R10_ENVIRONMENTAL,
}

# Constitutionally-immutable object kinds (create-once, never edited in place).
IMMUTABLE_TYPES: frozenset[ObjectType] = frozenset(
    {ObjectType.IDENTITY, ObjectType.EXECUTIVE_DECISION}
)


# --------------------------------------------------------------------------- #
# Value objects (immutable)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class RelationshipEdge:
    rel_type: RelationshipType
    target: str  # handle of the target object (reference, not a copy — OL7)
    weight: float = 1.0


@dataclass(frozen=True, slots=True)
class CognitiveObject:
    """One immutable *version* of a cognitive object (the substrate, Phase 1.5 P.3).

    A mutation produces a new version; the sequence of versions is the history.
    ``payload`` is opaque to the manager (engine-owned semantics).
    """

    handle: str
    type: ObjectType
    region: Region
    version: int
    status: ObjectStatus
    immutable: bool
    payload: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    confidence: float | None = None
    salience: float = 0.0
    relationships: tuple[RelationshipEdge, ...] = ()
    provenance: str = ""
    created_seq: int = 0
    modified_seq: int = 0
    created_at: datetime = field(default_factory=_utcnow)
    modified_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True, slots=True)
class StateChange:
    handle: str
    op: str  # created | updated | superseded | retracted
    from_version: int
    to_version: int
    seq: int
    at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True, slots=True)
class StateDiff:
    handle: str
    from_version: int
    to_version: int
    changed_fields: Mapping[str, tuple[Any, Any]]
    added_relationships: tuple[RelationshipEdge, ...]
    removed_relationships: tuple[RelationshipEdge, ...]


@dataclass(frozen=True, slots=True)
class StateSnapshot:
    snapshot_id: str
    seq: int  # logical time the snapshot is consistent with
    digest: str
    objects: tuple[CognitiveObject, ...]  # current versions
    created_at: datetime = field(default_factory=_utcnow)


@dataclass(frozen=True, slots=True)
class CommitResult:
    seq: int
    versions: Mapping[str, int]  # handle -> new version
    changes: tuple[StateChange, ...]


@dataclass(frozen=True, slots=True)
class StateMetricsSnapshot:
    object_count: int
    version_count: int
    by_type: Mapping[str, int]
    by_region: Mapping[str, int]
    commits: int
    aborts: int
    conflicts: int
    rollbacks: int
    merges: int
    integrity_ok: bool


@dataclass(frozen=True, slots=True)
class StateHealthReport:
    healthy: bool
    detail: str
    object_count: int
    integrity_ok: bool
    checked_at: datetime = field(default_factory=_utcnow)


# --------------------------------------------------------------------------- #
# Abstractions
# --------------------------------------------------------------------------- #


@runtime_checkable
class InvariantValidator(Protocol):
    """A pluggable consistency check run at commit. Engines register semantic
    validators; the manager ships only structural ones (P1: no cognition here).
    """

    @property
    def name(self) -> str: ...
    def validate(self, objects: Mapping[str, CognitiveObject]) -> None: ...


@runtime_checkable
class StateRepository(Protocol):
    def put_version(self, obj: CognitiveObject) -> None: ...
    def current(self, handle: str) -> CognitiveObject: ...
    def versions(self, handle: str) -> Sequence[CognitiveObject]: ...
    def exists(self, handle: str) -> bool: ...
    def all_current(self) -> Sequence[CognitiveObject]: ...
    def query(
        self, *, region: Region | None = None, type: ObjectType | None = None,
        status: ObjectStatus | None = None,
    ) -> Sequence[CognitiveObject]: ...
