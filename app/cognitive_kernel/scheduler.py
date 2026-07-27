"""Kernel scheduler — execution infrastructure only (performs no cognition).

Supports immediate, delayed, background, periodic, event-driven, and
priority-driven execution. It is *deterministic by default*: work is driven by
explicit :meth:`tick`/:meth:`drain` (and, for event-driven tasks, :meth:`fire`),
so tests and replay are reproducible. An optional background thread
(:meth:`start`) ticks in real time for production; it changes timing, never
outcomes. Every scheduled unit runs inside an :class:`ExecutionContext`.
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field

from .contracts import (
    EventPriority,
    ExecutionContext,
    ScheduledFn,
    ScheduledHandle,
    Scheduler,
    ScheduleKind,
)


@dataclass
class _Task:
    id: str
    seq: int
    fn: ScheduledFn
    context: ExecutionContext
    kind: ScheduleKind
    priority: EventPriority
    due: float  # monotonic seconds; float("inf") for event-driven
    interval: float | None
    cancelled: bool = field(default=False)

    def key(self) -> tuple[float, int, int]:
        return (self.due, int(self.priority), self.seq)


class _Handle(ScheduledHandle):
    __slots__ = ("_task",)

    def __init__(self, task: _Task) -> None:
        self._task = task

    @property
    def id(self) -> str:
        return self._task.id

    def cancel(self) -> None:
        self._task.cancelled = True


class KernelScheduler(Scheduler):
    def __init__(self, tick_interval: float = 0.01) -> None:
        self._tasks: dict[str, _Task] = {}
        self._counter = itertools.count()
        self._lock = threading.RLock()
        self._tick_interval = tick_interval
        self._thread: threading.Thread | None = None
        self._running = False

    def schedule(
        self,
        fn: ScheduledFn,
        context: ExecutionContext,
        *,
        kind: ScheduleKind = ScheduleKind.IMMEDIATE,
        delay: float = 0.0,
        interval: float | None = None,
        priority: EventPriority = EventPriority.NORMAL,
    ) -> ScheduledHandle:
        now = time.monotonic()
        if kind is ScheduleKind.IMMEDIATE:
            due = now
        elif kind is ScheduleKind.DELAYED:
            due = now + max(0.0, delay)
        elif kind is ScheduleKind.BACKGROUND:
            due, priority = now, EventPriority.BACKGROUND
        elif kind is ScheduleKind.PERIODIC:
            due = now + max(0.0, delay)
            interval = interval or self._tick_interval
        elif kind is ScheduleKind.PRIORITY:
            due = now
        elif kind is ScheduleKind.EVENT_DRIVEN:
            due = float("inf")  # only runs when explicitly fired
        else:  # pragma: no cover - exhaustive
            due = now
        task = _Task(
            id=f"task-{next(self._counter)}",
            seq=next(self._counter),
            fn=fn,
            context=context,
            kind=kind,
            priority=priority,
            due=due,
            interval=interval,
        )
        with self._lock:
            self._tasks[task.id] = task
        return _Handle(task)

    def fire(self, handle_id: str) -> bool:
        """Run an EVENT_DRIVEN task now (the event-driven trigger)."""
        with self._lock:
            task = self._tasks.get(handle_id)
            if task is None or task.cancelled:
                return False
        self._run(task)
        with self._lock:
            self._tasks.pop(handle_id, None)
        return True

    def tick(self, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        with self._lock:
            due = sorted(
                (t for t in self._tasks.values() if not t.cancelled and t.due <= now),
                key=_Task.key,
            )
        ran = 0
        for task in due:
            self._run(task)
            ran += 1
            with self._lock:
                if task.interval is not None and not task.cancelled:
                    task.due = now + task.interval  # reschedule periodic
                else:
                    self._tasks.pop(task.id, None)
        return ran

    def drain(self) -> int:
        """Run everything currently due; safe termination for non-periodic work."""
        total = 0
        while True:
            ran = self.tick()
            total += ran
            with self._lock:
                pending_due = any(
                    (not t.cancelled and t.interval is None and t.due <= time.monotonic())
                    for t in self._tasks.values()
                )
            if not pending_due:
                break
        return total

    def _run(self, task: _Task) -> None:
        if task.cancelled:
            return
        task.fn(task.context)

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True

        def loop() -> None:
            while True:
                with self._lock:
                    if not self._running:
                        return
                self.tick()
                time.sleep(self._tick_interval)

        self._thread = threading.Thread(target=loop, name="kernel-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._running = False
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
            self._thread = None
