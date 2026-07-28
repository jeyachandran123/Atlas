"""The Cognitive State Manager — owner of the Cognitive State lifecycle.

It stores, protects, versions, validates, and restores the Cognitive State. It
performs NO cognition (no reasoning, attention, planning, prediction, learning).
Future engines read and write the state ONLY through this manager's contracts;
they own behaviour, never state management (P1/OL1).

Built entirely on the kernel services (clock, events, ledger, checkpoints,
observability, health); it modifies nothing in the kernel or runtime.
"""

from __future__ import annotations

import dataclasses
import enum
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ..checkpoint import seal
from ..contracts import (
    Checkpoint,
    CognitiveEvent,
    EventPriority,
    HealthReport,
    HealthStatus,
    KernelServices,
)
from .concurrency import LockManager
from .contracts import (
    IMMUTABLE_TYPES,
    TYPE_REGION,
    CognitiveObject,
    CommitResult,
    InvariantValidator,
    ObjectStatus,
    ObjectType,
    Region,
    RelationshipEdge,
    RelationshipType,
    StateChange,
    StateDiff,
    StateHealthReport,
    StateMetricsSnapshot,
    StateSnapshot,
)
from .diff import diff_objects, diff_snapshots
from .errors import (
    ImmutableObjectError,
    ObjectNotFound,
    StateConflictError,
    StateConsistencyError,
    StateError,
)
from .invariants import InvariantEngine
from .objects import from_dict, to_dict
from .repository import InMemoryStateRepository
from .security import StateSecurity
from .serialization import deserialize_snapshot, digest_objects, make_snapshot, serialize_snapshot
from .transaction import StateTransaction


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StateLifecycle(enum.Enum):
    CREATED = "created"
    ACTIVE = "active"
    STOPPED = "stopped"


@dataclasses.dataclass(frozen=True, slots=True)
class StateConfig:
    security_enforce: bool = False
    checkpoint_owner: str = "cognitive_state"


@dataclasses.dataclass(slots=True)
class _Draft:
    base: CognitiveObject | None
    handle: str
    type: ObjectType
    region: Region
    status: ObjectStatus
    payload: dict[str, Any]
    confidence: float | None
    salience: float
    relationships: list[RelationshipEdge]
    provenance: str
    immutable: bool
    op: str

    @classmethod
    def from_base(cls, base: CognitiveObject) -> "_Draft":
        return cls(
            base=base, handle=base.handle, type=base.type, region=base.region,
            status=base.status, payload=dict(base.payload), confidence=base.confidence,
            salience=base.salience, relationships=list(base.relationships),
            provenance=base.provenance, immutable=base.immutable, op="updated",
        )


class CognitiveStateManager:
    def __init__(self, services: KernelServices, config: StateConfig | None = None) -> None:
        self._services = services
        self._config = config or StateConfig()
        self._repo = InMemoryStateRepository()
        self._invariants = InvariantEngine()
        self._locks = LockManager()
        self._security = StateSecurity(enforce=self._config.security_enforce)
        self._lifecycle = StateLifecycle.CREATED
        self._commit_lock = threading.RLock()
        self._recent_changes: deque[StateChange] = deque(maxlen=1024)
        self._commits = 0
        self._aborts = 0
        self._conflicts = 0
        self._rollbacks = 0
        self._merges = 0
        self._log = services.observability.logger("cognitive_state")
        services.health.register_probe("cognitive_state", self._health_probe)

    # --- lifecycle ------------------------------------------------------- #

    @property
    def lifecycle(self) -> StateLifecycle:
        return self._lifecycle

    def start(self) -> None:
        self._lifecycle = StateLifecycle.ACTIVE

    def stop(self) -> None:
        self._lifecycle = StateLifecycle.STOPPED

    def register_validator(self, validator: InvariantValidator) -> None:
        self._invariants.register(validator)

    # --- reads ----------------------------------------------------------- #

    def get(self, handle: str, context=None) -> CognitiveObject:
        if context is not None:
            self._security.check_read(context.security)
        return self._repo.current(handle)

    def get_version(self, handle: str, version: int) -> CognitiveObject:
        return self._repo.version_at(handle, version)

    def history(self, handle: str) -> Sequence[CognitiveObject]:
        return self._repo.versions(handle)

    def exists(self, handle: str) -> bool:
        return self._repo.exists(handle)

    def query(
        self, *, region: Region | None = None, type: ObjectType | None = None,
        status: ObjectStatus | None = None,
    ) -> Sequence[CognitiveObject]:
        return self._repo.query(region=region, type=type, status=status)

    def all_current(self) -> Sequence[CognitiveObject]:
        return self._repo.all_current()

    def relationships(self, handle: str) -> tuple[RelationshipEdge, ...]:
        return self._repo.current(handle).relationships

    def recent_changes(self) -> tuple[StateChange, ...]:
        return tuple(self._recent_changes)

    # --- transactions ---------------------------------------------------- #

    def begin_transaction(self, context) -> StateTransaction:
        return StateTransaction(self, context)

    def lock(self, handle: str):
        return self._locks.lock(handle)

    def _commit(self, tx: StateTransaction) -> CommitResult:
        with self._commit_lock:
            self._security.check_write(tx.context.security)
            # 1. Optimistic concurrency check (Phase 1.5 §12.6).
            for handle, expected in tx.reads.items():
                if not self._repo.exists(handle) or self._repo.current(handle).version != expected:
                    self._aborts += 1
                    self._conflicts += 1
                    current = self._repo.current(handle).version if self._repo.exists(handle) else None
                    raise StateConflictError(
                        f"{handle}: expected v{expected}, current v{current}"
                    )

            seq = self._services.clock.tick()
            drafts: dict[str, _Draft] = {}

            def draft_for(h: str) -> _Draft:
                if h in drafts:
                    return drafts[h]
                if not self._repo.exists(h):
                    raise ObjectNotFound(h)
                d = _Draft.from_base(self._repo.current(h))
                drafts[h] = d
                return d

            for op in tx.ops:
                if op.kind == "create":
                    if self._repo.exists(op.handle) or op.handle in drafts:
                        raise StateConsistencyError(f"create of existing handle {op.handle}")
                    drafts[op.handle] = _Draft(
                        base=None, handle=op.handle, type=op.type, region=TYPE_REGION[op.type],
                        status=op.status or ObjectStatus.ACTIVE, payload=dict(op.payload_replace or {}),
                        confidence=op.confidence, salience=op.salience or 0.0, relationships=[],
                        provenance=op.provenance, immutable=op.type in IMMUTABLE_TYPES, op="created",
                    )
                elif op.kind == "update":
                    d = draft_for(op.handle)
                    if op.payload_replace is not None:
                        d.payload = dict(op.payload_replace)
                    elif op.payload_merge:
                        d.payload.update(op.payload_merge)
                    if op.status is not None:
                        d.status = op.status
                    if op.confidence is not None:
                        d.confidence = op.confidence
                    if op.salience is not None:
                        d.salience = op.salience
                    if op.provenance:
                        d.provenance = op.provenance
                elif op.kind == "retract":
                    d = draft_for(op.handle)
                    d.status = ObjectStatus.RETRACTED
                    if d.op != "created":
                        d.op = "retracted"
                elif op.kind == "link":
                    d = draft_for(op.handle)
                    if op.edge is not None and op.edge not in d.relationships:
                        d.relationships.append(op.edge)
                elif op.kind == "supersede":
                    old = draft_for(op.handle)
                    old.status = ObjectStatus.SUPERSEDED
                    if old.op != "created":
                        old.op = "superseded"
                    drafts[op.new_handle] = _Draft(
                        base=None, handle=op.new_handle, type=op.type, region=TYPE_REGION[op.type],
                        status=ObjectStatus.ACTIVE, payload=dict(op.payload_replace or {}),
                        confidence=op.confidence, salience=op.salience or 0.0,
                        relationships=[RelationshipEdge(RelationshipType.SUPERSEDES, op.handle)],
                        provenance=op.provenance, immutable=op.type in IMMUTABLE_TYPES, op="created",
                    )

            # 2. Finalise drafts into exactly one new version each (OL4).
            new_versions: dict[str, CognitiveObject] = {}
            changes: list[StateChange] = []
            now = _now()
            for handle, d in drafts.items():
                if d.base is not None and d.base.immutable and d.status is not ObjectStatus.SUPERSEDED:
                    # Executive Decisions are immutable artifacts: supersede, never edit
                    # (Phase 1.5 Ch9). Identity may evolve only via the gated admin path
                    # (DeL1/ExL12). Marking an object SUPERSEDED is always permitted.
                    if d.type is ObjectType.EXECUTIVE_DECISION:
                        raise ImmutableObjectError(
                            "Executive Decisions are immutable; supersede with a new decision."
                        )
                    self._security.guards_immutable_evolution(tx.context.security, d.type)
                version = 1 if d.base is None else d.base.version + 1
                obj = CognitiveObject(
                    handle=handle, type=d.type, region=d.region, version=version,
                    status=d.status, immutable=d.immutable,
                    payload=MappingProxyType(dict(d.payload)), confidence=d.confidence,
                    salience=d.salience, relationships=tuple(d.relationships),
                    provenance=d.provenance,
                    created_seq=d.base.created_seq if d.base else seq, modified_seq=seq,
                    created_at=d.base.created_at if d.base else now, modified_at=now,
                )
                new_versions[handle] = obj
                changes.append(
                    StateChange(handle, d.op, d.base.version if d.base else 0, version, seq)
                )

            # 3. Consistency invariants over the prospective state (RL3).
            prospective = {o.handle: o for o in self._repo.all_current()}
            prospective.update(new_versions)
            try:
                self._invariants.validate(prospective)
            except StateError:
                self._aborts += 1
                raise  # nothing applied

            # 4. Apply atomically: versions, events (ledger), change tracking.
            for obj in new_versions.values():
                self._repo.put_version(obj)
            for ch in changes:
                obj = new_versions[ch.handle]
                self._emit(
                    f"cognitive_state.object.{ch.op}",
                    {"object": to_dict(obj)},
                    correlation_id=tx.context.correlation_id,
                )
                self._recent_changes.append(ch)
            self._commits += 1
            return CommitResult(seq, {h: o.version for h, o in new_versions.items()}, tuple(changes))

    # --- diff ------------------------------------------------------------ #

    def diff(self, handle: str, from_version: int, to_version: int) -> StateDiff:
        return diff_objects(
            self._repo.version_at(handle, from_version), self._repo.version_at(handle, to_version)
        )

    def snapshot_diff(self, a: StateSnapshot, b: StateSnapshot) -> dict:
        return diff_snapshots(a, b)

    # --- snapshots, checkpoints, restoration ----------------------------- #

    def snapshot(self) -> StateSnapshot:
        return make_snapshot(self._repo.all_current(), self._services.clock.current())

    def checkpoint(self) -> str:
        snap = self.snapshot()
        blob = serialize_snapshot(snap)
        cp = Checkpoint(
            checkpoint_id=f"{self._config.checkpoint_owner}@{snap.seq}:{snap.snapshot_id[:8]}",
            owner=self._config.checkpoint_owner, kind="cognitive_state",
            sequence=snap.seq, blob=blob, digest=seal(blob),
        )
        self._services.checkpoints.save(cp)
        self._emit("cognitive_state.checkpoint", {"id": cp.checkpoint_id, "seq": snap.seq}, correlation_id="state")
        return cp.checkpoint_id

    def restore(self, checkpoint_id: str | None = None) -> int:
        with self._commit_lock:
            if checkpoint_id is None:
                cp = self._services.checkpoints.latest(self._config.checkpoint_owner)
                if cp is None:
                    raise StateError("No cognitive-state checkpoint to restore.")
            else:
                cp = self._services.checkpoints.load(checkpoint_id)
            snap = deserialize_snapshot(cp.blob)
            self._repo.load(snap.objects)
            self._emit("cognitive_state.restored", {"seq": snap.seq}, correlation_id="state")
            return len(snap.objects)

    def serialize(self) -> bytes:
        return serialize_snapshot(self.snapshot())

    def restore_from_bytes(self, blob: bytes) -> int:
        with self._commit_lock:
            snap = deserialize_snapshot(blob)
            self._repo.load(snap.objects)
            return len(snap.objects)

    # --- rollback & merge ------------------------------------------------ #

    def rollback(self, handle: str, to_version: int, context) -> CognitiveObject:
        with self._commit_lock:
            self._security.check_write(context.security)
            old = self._repo.version_at(handle, to_version)
            cur = self._repo.current(handle)
            if cur.immutable:
                self._security.guards_immutable_evolution(context.security, cur.type)
            seq = self._services.clock.tick()
            now = _now()
            restored = dataclasses.replace(
                old, version=cur.version + 1, modified_seq=seq, modified_at=now,
                provenance=f"rollback to v{to_version}",
            )
            self._repo.put_version(restored)
            self._rollbacks += 1
            self._emit(
                "cognitive_state.object.updated", {"object": to_dict(restored)},
                correlation_id=context.correlation_id,
            )
            return restored

    def merge(self, incoming: StateSnapshot, context, *, strategy: str = "version_wins") -> int:
        with self._commit_lock:
            self._security.check_write(context.security)
            seq = self._services.clock.tick()
            now = _now()
            applied = 0
            for obj in incoming.objects:
                if not self._repo.exists(obj.handle):
                    merged = dataclasses.replace(obj, version=1, created_seq=seq, modified_seq=seq)
                    self._repo.put_version(merged)
                    self._emit("cognitive_state.object.created", {"object": to_dict(merged)}, correlation_id=context.correlation_id)
                    applied += 1
                    continue
                cur = self._repo.current(obj.handle)
                take_incoming = obj.version > cur.version if strategy == "version_wins" else strategy == "incoming_wins"
                if take_incoming:
                    if cur.immutable:
                        self._security.guards_immutable_evolution(context.security, cur.type)
                    merged = dataclasses.replace(
                        obj, version=cur.version + 1, created_seq=cur.created_seq,
                        created_at=cur.created_at, modified_seq=seq, modified_at=now,
                    )
                    self._repo.put_version(merged)
                    self._emit("cognitive_state.object.updated", {"object": to_dict(merged)}, correlation_id=context.correlation_id)
                    applied += 1
            self._merges += 1
            return applied

    # --- integrity, recovery, metrics, health --------------------------- #

    def verify_integrity(self) -> bool:
        ledger_ok = self._services.ledger.verify()
        # Recompute the current-state digest to prove the projection is coherent.
        _ = digest_objects(self._repo.all_current())
        return ledger_ok

    def recover(self) -> int:
        """Rebuild the projection from the ledger's state events (RL8)."""
        with self._commit_lock:
            if not self._services.ledger.verify():
                raise StateError("Ledger integrity failed; refusing to recover state.")
            temp = InMemoryStateRepository()
            applied = 0
            for entry in self._services.ledger.read():
                ev = entry.event
                if ev.type.startswith("cognitive_state.object.") and "object" in ev.payload:
                    temp.put_version(from_dict(ev.payload["object"]))
                    applied += 1
            self._repo = temp
            self._emit("cognitive_state.recovered", {"events": applied}, correlation_id="state")
            return applied

    def metrics(self) -> StateMetricsSnapshot:
        obj_count, ver_count, by_type, by_region = self._repo.counts()
        return StateMetricsSnapshot(
            object_count=obj_count, version_count=ver_count, by_type=by_type, by_region=by_region,
            commits=self._commits, aborts=self._aborts, conflicts=self._conflicts,
            rollbacks=self._rollbacks, merges=self._merges,
            integrity_ok=self._services.ledger.verify(),
        )

    def health(self) -> StateHealthReport:
        integrity = self._services.ledger.verify()
        obj_count = self._repo.counts()[0]
        healthy = self._lifecycle is StateLifecycle.ACTIVE and integrity
        return StateHealthReport(
            healthy=healthy,
            detail=f"{self._lifecycle.value}, integrity={'ok' if integrity else 'FAIL'}",
            object_count=obj_count, integrity_ok=integrity,
        )

    def diagnostics(self) -> dict:
        return {
            "lifecycle": self._lifecycle.value,
            "metrics": self.metrics(),
            "validators": self._invariants.validators(),
            "health": self.health().healthy,
        }

    # --- internals ------------------------------------------------------- #

    def _emit(self, event_type: str, payload: Mapping[str, Any], *, correlation_id: str) -> None:
        event = CognitiveEvent(
            event_id=uuid.uuid4().hex, type=event_type, sequence=self._services.clock.tick(),
            source="cognitive_state", correlation_id=correlation_id, payload=payload,
            priority=EventPriority.NORMAL,
        )
        self._services.events.publish(event)

    def _health_probe(self) -> HealthReport:
        integrity = self._services.ledger.verify()
        healthy = self._lifecycle is StateLifecycle.ACTIVE and integrity
        return HealthReport(
            component="cognitive_state",
            status=HealthStatus.HEALTHY if healthy else (
                HealthStatus.DEGRADED if self._lifecycle is StateLifecycle.CREATED else HealthStatus.UNHEALTHY
            ),
            detail=f"{self._lifecycle.value}",
            metrics={"objects": float(self._repo.counts()[0])},
        )
