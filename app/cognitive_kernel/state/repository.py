"""Versioned in-memory state repository (the materialised projection).

Stores the full version history of every object (OL4 — history is never lost).
The "current" object is the latest committed version. Thread-safe. This is the
manager's projection; the durable record is the kernel ledger (RL8).
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Sequence

from .contracts import CognitiveObject, ObjectStatus, ObjectType, Region, StateRepository
from .errors import ObjectNotFound, StateConsistencyError


class InMemoryStateRepository(StateRepository):
    def __init__(self) -> None:
        self._versions: dict[str, list[CognitiveObject]] = {}
        self._lock = threading.RLock()

    def put_version(self, obj: CognitiveObject) -> None:
        with self._lock:
            history = self._versions.get(obj.handle)
            if history is None:
                if obj.version != 1:
                    raise StateConsistencyError(
                        f"First version of {obj.handle} must be v1, got v{obj.version}"
                    )
                self._versions[obj.handle] = [obj]
            else:
                if obj.version != history[-1].version + 1:
                    raise StateConsistencyError(
                        f"Non-monotonic version for {obj.handle}: "
                        f"v{obj.version} after v{history[-1].version}"
                    )
                history.append(obj)

    def current(self, handle: str) -> CognitiveObject:
        with self._lock:
            history = self._versions.get(handle)
            if not history:
                raise ObjectNotFound(f"Unknown object: {handle}")
            return history[-1]

    def version_at(self, handle: str, version: int) -> CognitiveObject:
        with self._lock:
            for obj in self._versions.get(handle, []):
                if obj.version == version:
                    return obj
        raise ObjectNotFound(f"Object {handle} has no version {version}")

    def versions(self, handle: str) -> Sequence[CognitiveObject]:
        with self._lock:
            return tuple(self._versions.get(handle, ()))

    def exists(self, handle: str) -> bool:
        with self._lock:
            return handle in self._versions

    def all_current(self) -> Sequence[CognitiveObject]:
        with self._lock:
            return tuple(h[-1] for h in self._versions.values())

    def query(
        self,
        *,
        region: Region | None = None,
        type: ObjectType | None = None,
        status: ObjectStatus | None = None,
    ) -> Sequence[CognitiveObject]:
        with self._lock:
            out = []
            for history in self._versions.values():
                obj = history[-1]
                if region is not None and obj.region is not region:
                    continue
                if type is not None and obj.type is not type:
                    continue
                if status is not None and obj.status is not status:
                    continue
                out.append(obj)
            return tuple(out)

    def counts(self) -> tuple[int, int, dict[str, int], dict[str, int]]:
        with self._lock:
            by_type: dict[str, int] = defaultdict(int)
            by_region: dict[str, int] = defaultdict(int)
            version_count = 0
            for history in self._versions.values():
                cur = history[-1]
                by_type[cur.type.value] += 1
                by_region[cur.region.value] += 1
                version_count += len(history)
            return len(self._versions), version_count, dict(by_type), dict(by_region)

    def load(self, objects: Sequence[CognitiveObject]) -> None:
        """Replace the projection with the given current versions (restore)."""
        with self._lock:
            self._versions = {obj.handle: [obj] for obj in objects}

    def clear(self) -> None:
        with self._lock:
            self._versions = {}
