"""Concurrency control: pessimistic per-handle locks + OCC support.

Optimistic concurrency (compare expected version at commit) is the default path
(Phase 1.5 §12.6). Pessimistic per-handle locks are available for critical
read-modify-write sections. A single global commit lock serialises transaction
commits (isolation, RL3).
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator


class LockManager:
    def __init__(self) -> None:
        self._locks: dict[str, threading.RLock] = {}
        self._guard = threading.Lock()

    def _lock_for(self, handle: str) -> threading.RLock:
        with self._guard:
            lock = self._locks.get(handle)
            if lock is None:
                lock = threading.RLock()
                self._locks[handle] = lock
            return lock

    @contextmanager
    def lock(self, handle: str) -> Iterator[None]:
        lock = self._lock_for(handle)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()

    @contextmanager
    def lock_many(self, handles: list[str]) -> Iterator[None]:
        # Acquire in a deterministic order to avoid deadlock.
        acquired = []
        try:
            for h in sorted(set(handles)):
                lk = self._lock_for(h)
                lk.acquire()
                acquired.append(lk)
            yield
        finally:
            for lk in reversed(acquired):
                lk.release()
