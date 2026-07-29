"""Architecture tests — Learning commits durable change; it performs no faculty's work."""

from __future__ import annotations

import ast
import os

import app.cognitive_kernel.engines.learning as lnpkg
from app.cognitive_kernel.contracts import CognitiveEngine
from app.cognitive_kernel.runtime.contracts import ExecutableEngine
from app.cognitive_kernel.state import CognitiveStateManager
from app.cognitive_kernel.engines.learning import LearningEngine
from app.cognitive_kernel.engines.learning.ports import RuntimeAuthorizationPort

from ._ln import episodes, make_learning, teardown

_PKG = os.path.dirname(lnpkg.__file__)

# Sibling engines Learning must never import or call directly. Authorization is
# routed to the Executive via the Runtime; inputs are read from State/Ledger.
_FORBIDDEN = {"attention", "reasoning", "executive", "prediction", "metacognition", "meta_cognition", "development"}
# Faculty verbs Learning must never expose (it commits durable change; it performs no faculty).
_FORBIDDEN_VERBS = ("reason", "predict", "attend", "select", "ignite", "govern", "allocate",
                    "decide", "reflect", "forecast", "oversee")


def _modules() -> dict[str, str]:
    return {fn[:-3]: os.path.join(_PKG, fn) for fn in os.listdir(_PKG)
            if fn.endswith(".py") and fn != "__init__.py"}


def _sibling_imports(path: str) -> set[str]:
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    deps: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                deps.add(node.module.split(".")[0])
            else:
                for a in node.names:
                    deps.add(a.name.split(".")[0])
    return deps


def _all_imported(path: str) -> set[str]:
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.update(node.module.split("."))
        elif isinstance(node, ast.Import):
            for a in node.names:
                names.update(a.name.split("."))
    return names


def test_no_circular_dependencies() -> None:
    mods = _modules()
    graph = {n: (_sibling_imports(p) & set(mods)) for n, p in mods.items()}
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
    assert seen == len(graph), "circular dependency among learning modules"


def test_contracts_is_pure_abi() -> None:
    assert _sibling_imports(os.path.join(_PKG, "contracts.py")) == set()


def test_learning_imports_no_sibling_engine() -> None:
    for name, path in _modules().items():
        leaked = _all_imported(path) & _FORBIDDEN
        assert not leaked, f"{name}.py imports sibling engine(s) it must not know: {leaked}"


def test_learning_performs_no_faculty_work() -> None:
    for verb in _FORBIDDEN_VERBS:
        assert not hasattr(LearningEngine, verb), f"Learning must not expose {verb!r}"


def test_state_changes_flow_through_the_manager() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        assert isinstance(learn._state, CognitiveStateManager)     # noqa: SLF001 - only via the manager
        assert isinstance(learn, ExecutableEngine) and isinstance(learn, CognitiveEngine)
        assert "learning" in rt._orchestrator.names()               # noqa: SLF001 - executes via runtime
        assert "learning" in kernel.engine_registry().names()       # registered with kernel
        assert isinstance(learn._auth, RuntimeAuthorizationPort)    # noqa: SLF001 - authorization via runtime
    finally:
        teardown(kernel, rt, state, learn)


def test_every_revision_has_provenance_and_is_reversible() -> None:
    kernel, rt, state, learn, ctx, admin = make_learning()
    try:
        episodes(state, ctx, "verified_fact", 3)
        learn.learn(ctx)
        committed = [r for r in learn.records() if r.committed and r.revision]
        assert committed
        for r in committed:
            assert r.provenance and r.reversible and r.revision.reversible  # LeL13/LeL24
            assert r.record_id in learn._reversible                          # noqa: SLF001 - rollback available
    finally:
        teardown(kernel, rt, state, learn)
