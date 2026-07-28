"""Cognitive state transactions — staged, atomic, versioned, OCC-checked.

A transaction stages mutations; :meth:`commit` hands them to the manager which
applies them atomically (RL3), producing exactly one new version per touched
object (OL4), enforcing invariants (consistency) and optimistic version conflict
detection (Phase 1.5 §12.6). Nothing is applied unless every check passes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from ..contracts import ExecutionContext
from .contracts import (
    CognitiveObject,
    CommitResult,
    ObjectStatus,
    ObjectType,
    RelationshipEdge,
    RelationshipType,
)
from .errors import TransactionError


@dataclass(slots=True)
class _Op:
    kind: str  # create | update | supersede | retract | link
    handle: str
    type: ObjectType | None = None
    new_handle: str | None = None
    payload_merge: Mapping[str, Any] | None = None
    payload_replace: Mapping[str, Any] | None = None
    status: ObjectStatus | None = None
    confidence: float | None = None
    salience: float | None = None
    edge: RelationshipEdge | None = None
    provenance: str = ""


class StateTransaction:
    def __init__(self, manager: Any, context: ExecutionContext) -> None:
        self._manager = manager
        self.context = context
        self.ops: list[_Op] = []
        self.reads: dict[str, int] = {}  # handle -> expected version (OCC)
        self._done = False

    # --- reads (record expected versions for OCC) ------------------------ #

    def read(self, handle: str) -> CognitiveObject:
        obj = self._manager._repo.current(handle)
        self.reads[handle] = obj.version
        return obj

    # --- staged mutations ------------------------------------------------ #

    def create(
        self,
        type: ObjectType,
        *,
        handle: str | None = None,
        payload: Mapping[str, Any] | None = None,
        status: ObjectStatus = ObjectStatus.ACTIVE,
        confidence: float | None = None,
        salience: float = 0.0,
        relationships: tuple[RelationshipEdge, ...] = (),
        provenance: str = "",
    ) -> str:
        h = handle or uuid.uuid4().hex
        self.ops.append(
            _Op(
                "create", h, type=type, payload_replace=payload, status=status,
                confidence=confidence, salience=salience, provenance=provenance,
            )
        )
        for edge in relationships:
            self.ops.append(_Op("link", h, edge=edge))
        return h

    def update(
        self,
        handle: str,
        *,
        expected_version: int | None = None,
        payload_merge: Mapping[str, Any] | None = None,
        payload_replace: Mapping[str, Any] | None = None,
        status: ObjectStatus | None = None,
        confidence: float | None = None,
        salience: float | None = None,
        provenance: str = "",
    ) -> None:
        if expected_version is not None:
            self.reads[handle] = expected_version
        self.ops.append(
            _Op(
                "update", handle, payload_merge=payload_merge, payload_replace=payload_replace,
                status=status, confidence=confidence, salience=salience, provenance=provenance,
            )
        )

    def supersede(
        self,
        handle: str,
        type: ObjectType,
        *,
        payload: Mapping[str, Any] | None = None,
        confidence: float | None = None,
        salience: float = 0.0,
        provenance: str = "",
    ) -> str:
        new_handle = uuid.uuid4().hex
        self.ops.append(
            _Op(
                "supersede", handle, new_handle=new_handle, type=type, payload_replace=payload,
                confidence=confidence, salience=salience, provenance=provenance,
            )
        )
        return new_handle

    def retract(self, handle: str) -> None:
        self.ops.append(_Op("retract", handle))

    def link(self, src: str, rel_type: RelationshipType, dst: str, weight: float = 1.0) -> None:
        self.ops.append(_Op("link", src, edge=RelationshipEdge(rel_type, dst, weight)))

    # --- terminal -------------------------------------------------------- #

    def commit(self) -> CommitResult:
        if self._done:
            raise TransactionError("Transaction already finalised.")
        self._done = True
        return self._manager._commit(self)

    def abort(self) -> None:
        self._done = True
        self.ops.clear()
