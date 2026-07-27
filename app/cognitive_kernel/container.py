"""Dependency-injection container.

Everything inside the kernel depends on *abstractions* (contracts), resolved
here (P6/OL8). No engine instantiates another engine; no singleton business
logic; no global mutable state. Registration is explicit (constructor-style
factories receive the container) — no reflection magic, so resolution is
deterministic and auditable.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from .contracts import Container
from .errors import DependencyResolutionError


class KernelContainer(Container):
    __slots__ = ("_factories", "_singletons", "_instances", "_resolving", "_lock")

    def __init__(self) -> None:
        self._factories: dict[type, Callable[[Container], Any]] = {}
        self._singletons: dict[type, bool] = {}
        self._instances: dict[type, Any] = {}
        self._resolving: set[type] = set()
        self._lock = threading.RLock()

    def register(
        self,
        contract: type,
        factory: Callable[[Container], Any],
        *,
        singleton: bool = True,
    ) -> None:
        with self._lock:
            self._factories[contract] = factory
            self._singletons[contract] = singleton
            self._instances.pop(contract, None)

    def register_instance(self, contract: type, instance: Any) -> None:
        with self._lock:
            self._instances[contract] = instance
            self._singletons[contract] = True
            self._factories.pop(contract, None)

    def has(self, contract: type) -> bool:
        with self._lock:
            return contract in self._instances or contract in self._factories

    def resolve(self, contract: type) -> Any:
        with self._lock:
            if contract in self._instances:
                return self._instances[contract]
            if contract not in self._factories:
                raise DependencyResolutionError(
                    f"No registration for {getattr(contract, '__name__', contract)!r}"
                )
            if contract in self._resolving:
                cycle = " -> ".join(getattr(c, "__name__", str(c)) for c in self._resolving)
                raise DependencyResolutionError(f"Circular dependency: {cycle} -> {contract}")
            self._resolving.add(contract)
            try:
                instance = self._factories[contract](self)
            finally:
                self._resolving.discard(contract)
            if self._singletons.get(contract, True):
                self._instances[contract] = instance
            return instance
