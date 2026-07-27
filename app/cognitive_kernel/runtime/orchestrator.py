"""Engine orchestrator — the runtime's execution routing table.

The runtime selects *which* registered engine executes, *when*, and *under what
context* — but never performs cognition. This is a distinct concern from the
kernel's Engine Registry (which owns lifecycle + DI): this table maps an engine
name to its :class:`ExecutableEngine` execution handle. Engines register here so
the runtime can route work to them; they never call one another directly.
"""

from __future__ import annotations

import threading
from typing import Any, Mapping

from ..contracts import ExecutionContext
from .contracts import ExecutableEngine
from .errors import EngineNotFound


class _CallableEngine:
    """Adapts a plain task callable into an ExecutableEngine (for anonymous work)."""

    __slots__ = ("_task",)

    def __init__(self, task) -> None:
        self._task = task

    def execute(self, operation: str, payload: Mapping[str, Any], context: ExecutionContext) -> Any:
        return self._task(context)


class EngineOrchestrator:
    def __init__(self) -> None:
        self._engines: dict[str, ExecutableEngine] = {}
        self._lock = threading.Lock()

    def register(self, name: str, engine: ExecutableEngine) -> None:
        if not isinstance(engine, ExecutableEngine):
            raise TypeError(f"{name!r} does not implement ExecutableEngine")
        with self._lock:
            self._engines[name] = engine

    def unregister(self, name: str) -> None:
        with self._lock:
            self._engines.pop(name, None)

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._engines

    def resolve(self, name: str) -> ExecutableEngine:
        with self._lock:
            if name not in self._engines:
                raise EngineNotFound(f"No executable engine registered: {name!r}")
            return self._engines[name]

    def names(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._engines.keys())

    @staticmethod
    def for_task(task) -> ExecutableEngine:
        """Wrap a raw task callable as an ExecutableEngine."""
        return _CallableEngine(task)
