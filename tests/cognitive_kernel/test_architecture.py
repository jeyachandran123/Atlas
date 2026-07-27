"""Architecture tests — enforce the kernel's structural invariants.

These guard the constitutional/engineering rules mechanically:
  * no circular dependencies among kernel modules;
  * the ABI (``contracts``) depends on no concrete kernel module;
  * the kernel performs no cognition (hosts zero engines by default; exposes no
    cognitive verbs);
  * the ledger is append-only (no mutation API);
  * infrastructure is resolvable via DI and satisfies its Protocol.
"""

from __future__ import annotations

import ast
import os

import app.cognitive_kernel as ck
from app.cognitive_kernel import Bootstrapper, KernelConfig
from app.cognitive_kernel import contracts as C

_PKG_DIR = os.path.dirname(ck.__file__)


def _kernel_modules() -> dict[str, str]:
    out: dict[str, str] = {}
    for fn in os.listdir(_PKG_DIR):
        if fn.endswith(".py") and fn != "__init__.py":
            out[fn[:-3]] = os.path.join(_PKG_DIR, fn)
    return out


def _relative_imports(path: str) -> set[str]:
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    deps: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level and node.level >= 1:
            if node.module:  # from .events import X
                deps.add(node.module.split(".")[0])
            else:  # from . import contracts, ledger
                for alias in node.names:
                    deps.add(alias.name.split(".")[0])
    return deps


def test_no_circular_dependencies_among_kernel_modules() -> None:
    modules = _kernel_modules()
    graph = {name: (_relative_imports(path) & set(modules)) for name, path in modules.items()}
    # Kahn's algorithm: a full topological order exists iff the graph is a DAG.
    indeg = {n: 0 for n in graph}
    for n, deps in graph.items():
        for d in deps:
            indeg[n] += 1  # n depends on d  (edge d -> n)
    # recompute indegree correctly on edge d->n
    indeg = {n: 0 for n in graph}
    adj: dict[str, list[str]] = {n: [] for n in graph}
    for n, deps in graph.items():
        for d in deps:
            adj[d].append(n)
            indeg[n] += 1
    ready = [n for n, d in indeg.items() if d == 0]
    seen = 0
    while ready:
        node = ready.pop()
        seen += 1
        for nxt in adj[node]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
    assert seen == len(graph), "circular dependency detected among kernel modules"


def test_contracts_is_pure_abi_no_concrete_deps() -> None:
    # The ABI module must import no sibling kernel module (pure abstractions).
    assert _relative_imports(os.path.join(_PKG_DIR, "contracts.py")) == set()


def test_kernel_hosts_no_engines_and_exposes_no_cognition() -> None:
    kernel = Bootstrapper().boot(
        KernelConfig(identity_name="Atlas", identity_core={"safety_first": True})
    )
    try:
        # No cognitive engine is registered by the foundation.
        assert list(kernel.engine_registry().names()) == []
        # The kernel exposes infrastructure, not cognition.
        for verb in ("reason", "attend", "plan", "predict", "learn", "reflect", "decide"):
            assert not hasattr(kernel, verb), f"kernel must not expose cognitive verb {verb!r}"
    finally:
        kernel.shutdown()


def test_ledger_is_append_only() -> None:
    from app.cognitive_kernel.ledger import CognitiveLedger

    forbidden = ("update", "delete", "remove", "set", "insert", "overwrite", "mutate")
    for name in forbidden:
        assert not hasattr(CognitiveLedger, name), f"ledger must not expose {name!r}"


def test_all_infrastructure_resolves_and_satisfies_contracts() -> None:
    kernel = Bootstrapper().boot(KernelConfig(identity_name="Atlas"))
    try:
        c = kernel.container
        pairs = [
            (C.LogicalClock, c.resolve(C.LogicalClock)),
            (C.EventBus, c.resolve(C.EventBus)),
            (C.Ledger, c.resolve(C.Ledger)),
            (C.Scheduler, c.resolve(C.Scheduler)),
            (C.HealthMonitor, c.resolve(C.HealthMonitor)),
            (C.CheckpointStore, c.resolve(C.CheckpointStore)),
            (C.IdentityProvider, c.resolve(C.IdentityProvider)),
            (C.ConstitutionRegistry, c.resolve(C.ConstitutionRegistry)),
            (C.CapabilityRegistry, c.resolve(C.CapabilityRegistry)),
            (C.EngineRegistry, c.resolve(C.EngineRegistry)),
        ]
        for contract, instance in pairs:
            assert isinstance(instance, contract), f"{instance!r} does not satisfy {contract}"
    finally:
        kernel.shutdown()


def test_boot_history_follows_os_lifecycle() -> None:
    kernel = Bootstrapper().boot(KernelConfig(identity_name="Atlas"))
    try:
        transitions = [t[1] for t in kernel.lifecycle.history]
        assert transitions == [
            C.KernelState.INITIALIZING,
            C.KernelState.STARTING,
            C.KernelState.RUNNING,
        ]
    finally:
        kernel.shutdown()
