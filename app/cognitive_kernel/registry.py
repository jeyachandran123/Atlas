"""Engine and capability registries.

The **Engine Registry** hosts future cognitive engines by *contract*: each
engine self-registers metadata + a factory (never a concrete singleton). The
kernel computes a deterministic initialization order by topologically sorting
declared dependencies (cycles are rejected). No engine instantiates another
engine — they are all resolved by the kernel and wired only via the event bus.

The **Capability Registry** is the integration seam to the existing UnityWorks
platforms (Workspace, Knowledge, Semantic, Conversation, Generation). The kernel
*discovers* faculties here; it does not duplicate the platforms' own registry.
An optional external discovery hook lets the real platform registry be plugged
in without modifying the kernel.
"""

from __future__ import annotations

import threading
from typing import Callable, Sequence

from .contracts import Capability, CapabilityRegistry, EngineFactory, EngineMetadata, EngineRegistry
from .errors import EngineRegistrationError, KernelError


class KernelEngineRegistry(EngineRegistry):
    def __init__(self) -> None:
        self._metadata: dict[str, EngineMetadata] = {}
        self._factories: dict[str, EngineFactory] = {}
        self._lock = threading.Lock()

    def register(self, metadata: EngineMetadata, factory: EngineFactory) -> None:
        with self._lock:
            if metadata.name in self._metadata:
                raise EngineRegistrationError(f"Engine already registered: {metadata.name}")
            self._metadata[metadata.name] = metadata
            self._factories[metadata.name] = factory

    def metadata(self, name: str) -> EngineMetadata:
        with self._lock:
            if name not in self._metadata:
                raise EngineRegistrationError(f"Unknown engine: {name}")
            return self._metadata[name]

    def factory(self, name: str) -> EngineFactory:
        with self._lock:
            if name not in self._factories:
                raise EngineRegistrationError(f"Unknown engine: {name}")
            return self._factories[name]

    def names(self) -> Sequence[str]:
        with self._lock:
            return tuple(self._metadata.keys())

    def initialization_order(self) -> Sequence[str]:
        """Deterministic topological sort over ``depends_on`` (Kahn's algorithm)."""
        with self._lock:
            meta = dict(self._metadata)
        # Validate dependency references.
        for name, m in meta.items():
            for dep in m.depends_on:
                if dep not in meta:
                    raise EngineRegistrationError(
                        f"Engine {name!r} depends on unregistered engine {dep!r}"
                    )
        indegree = {n: 0 for n in meta}
        adj: dict[str, list[str]] = {n: [] for n in meta}
        for name, m in meta.items():
            for dep in m.depends_on:
                adj[dep].append(name)
                indegree[name] += 1
        # Ready set processed in sorted order → deterministic output.
        ready = sorted(n for n, d in indegree.items() if d == 0)
        order: list[str] = []
        while ready:
            node = ready.pop(0)
            order.append(node)
            for nxt in sorted(adj[node]):
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    ready.append(nxt)
            ready.sort()
        if len(order) != len(meta):
            raise EngineRegistrationError("Engine dependency graph has a cycle")
        return tuple(order)


ExternalDiscovery = Callable[[], Sequence[Capability]]


class KernelCapabilityRegistry(CapabilityRegistry):
    def __init__(self, external_discovery: ExternalDiscovery | None = None) -> None:
        self._caps: dict[str, Capability] = {}
        self._external = external_discovery
        self._lock = threading.Lock()

    def register(self, capability: Capability) -> None:
        with self._lock:
            self._caps[capability.name] = capability

    def discover(self) -> Sequence[Capability]:
        # Merge locally-registered capabilities with those discovered from the
        # existing platforms (the seam). Local registrations win on conflict.
        discovered: dict[str, Capability] = {}
        if self._external is not None:
            for cap in self._external():
                discovered[cap.name] = cap
        with self._lock:
            discovered.update(self._caps)
        return tuple(discovered.values())

    def get(self, name: str) -> Capability:
        for cap in self.discover():
            if cap.name == name:
                return cap
        raise KernelError(f"Unknown capability: {name}")

    def has(self, name: str) -> bool:
        return any(cap.name == name for cap in self.discover())
