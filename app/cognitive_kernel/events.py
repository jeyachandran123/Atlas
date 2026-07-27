"""The Cognitive Event Bus — the nervous system.

Every engine communicates ONLY through events (never direct engine-to-engine
calls, P1/P6). The default bus dispatches synchronously and deterministically
(a hard requirement: the kernel must be deterministic), preserves publish order
via logical sequence, and keeps an ordered log for replay. It supports typed
events, priority filtering, correlation/causation ids, subscriptions, arbitrary
predicate filters, and is serialisation-ready for future distributed execution.
"""

from __future__ import annotations

import threading
from typing import Callable

from .contracts import (
    CognitiveEvent,
    EventBus,
    EventFilter,
    EventHandler,
    EventPriority,
    Subscription,
)


class _Subscription(Subscription):
    __slots__ = ("id", "event_type", "handler", "predicate", "max_priority", "_bus", "_active")

    def __init__(
        self,
        sub_id: int,
        event_type: str,
        handler: EventHandler,
        predicate: EventFilter | None,
        max_priority: EventPriority,
        bus: "CognitiveEventBus",
    ) -> None:
        self.id = sub_id
        self.event_type = event_type
        self.handler = handler
        self.predicate = predicate
        self.max_priority = max_priority
        self._bus = bus
        self._active = True

    def matches(self, event: CognitiveEvent) -> bool:
        if not self._active:
            return False
        if self.event_type != "*" and self.event_type != event.type:
            return False
        if int(event.priority) > int(self.max_priority):
            return False
        if self.predicate is not None and not self.predicate(event):
            return False
        return True

    def unsubscribe(self) -> None:
        self._active = False
        self._bus._remove(self)


ErrorHook = Callable[[CognitiveEvent, EventHandler, BaseException], None]


class CognitiveEventBus(EventBus):
    def __init__(self, on_error: ErrorHook | None = None) -> None:
        self._subs: list[_Subscription] = []
        self._log: list[CognitiveEvent] = []
        self._next_sub = 0
        self._on_error = on_error
        self._lock = threading.RLock()

    def subscribe(
        self,
        event_type: str,
        handler: EventHandler,
        *,
        predicate: EventFilter | None = None,
        max_priority: EventPriority = EventPriority.BACKGROUND,
    ) -> Subscription:
        with self._lock:
            sub = _Subscription(self._next_sub, event_type, handler, predicate, max_priority, self)
            self._next_sub += 1
            self._subs.append(sub)
            return sub

    def _remove(self, sub: _Subscription) -> None:
        with self._lock:
            try:
                self._subs.remove(sub)
            except ValueError:
                pass

    def publish(self, event: CognitiveEvent) -> None:
        # Snapshot subscribers under lock; dispatch outside to avoid re-entrancy
        # deadlocks while preserving deterministic (registration) order.
        with self._lock:
            self._log.append(event)
            targets = [s for s in self._subs if s.matches(event)]
        for sub in targets:
            try:
                sub.handler(event)
            except BaseException as exc:  # a bad handler must not break the nervous system
                if self._on_error is not None:
                    self._on_error(event, sub.handler, exc)

    def replay(self, handler: EventHandler, *, since: int = 0) -> int:
        with self._lock:
            events = [e for e in self._log if e.sequence > since]
        count = 0
        for event in events:
            handler(event)
            count += 1
        return count
