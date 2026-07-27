"""The Cognitive Ledger — append-only, event-sourced, tamper-evident.

Every cognitive operation is recorded here (OL4/OL6/RL8). The ledger is the
substrate for audit, replay, recovery, learning, meta-cognition, and
development. It is **never** mutated: there is no update or delete. Integrity is
a sha256 hash chain — each entry's digest covers the previous digest plus the
event, so any tampering with history is detectable (Phase 1.5 Ch10 sealing).
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Iterable

from .contracts import CognitiveEvent, Ledger, LedgerEntry
from .errors import LedgerIntegrityError

_GENESIS = "0" * 64


def _digest(previous: str, event: CognitiveEvent) -> str:
    canonical = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{previous}|{canonical}".encode("utf-8")).hexdigest()


class CognitiveLedger(Ledger):
    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []
        self._last_digest = _GENESIS
        self._last_sequence = 0
        self._lock = threading.Lock()

    def append(self, event: CognitiveEvent) -> LedgerEntry:
        with self._lock:
            if event.sequence <= self._last_sequence:
                raise LedgerIntegrityError(
                    f"Non-monotonic sequence: {event.sequence} <= {self._last_sequence}"
                )
            digest = _digest(self._last_digest, event)
            entry = LedgerEntry(sequence=event.sequence, event=event, digest=digest)
            self._entries.append(entry)
            self._last_digest = digest
            self._last_sequence = event.sequence
            return entry

    def read(self, *, since: int = 0, until: int | None = None) -> Iterable[LedgerEntry]:
        with self._lock:
            snapshot = list(self._entries)
        for entry in snapshot:
            if entry.sequence <= since:
                continue
            if until is not None and entry.sequence > until:
                break
            yield entry

    def head(self) -> int:
        with self._lock:
            return self._last_sequence

    def verify(self) -> bool:
        with self._lock:
            previous = _GENESIS
            for entry in self._entries:
                expected = _digest(previous, entry.event)
                if expected != entry.digest:
                    return False
                previous = entry.digest
        return True
