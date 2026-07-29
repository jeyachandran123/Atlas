"""Architecture tests — Development proposes; it performs no cognition and changes nothing."""

from __future__ import annotations

import ast
import os

import app.cognitive_kernel.engines.development as dvpkg
from app.cognitive_kernel.contracts import CognitiveEngine
from app.cognitive_kernel.runtime.contracts import ExecutableEngine
from app.cognitive_kernel.state import CognitiveStateManager
from app.cognitive_kernel.engines.development import DevelopmentEngine
from app.cognitive_kernel.engines.development.ports import RuntimeReviewPort

from ._dv import make_development, strong_reasoning, teardown

_PKG = os.path.dirname(dvpkg.__file__)

# Sibling engines Development must never import or call directly. It consumes evidence
# from the Ledger/State and routes review through the Runtime.
_FORBIDDEN = {"attention", "reasoning", "executive", "prediction", "metacognition", "meta_cognition", "learning"}
# Faculty verbs Development must never expose (it proposes; it performs no faculty).
_FORBIDDEN_VERBS = ("reason", "predict", "attend", "select", "ignite", "govern", "allocate",
                    "decide", "reflect", "forecast", "learn", "commit")


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
    assert seen == len(graph), "circular dependency among development modules"


def test_contracts_is_pure_abi() -> None:
    assert _sibling_imports(os.path.join(_PKG, "contracts.py")) == set()


def test_development_imports_no_sibling_engine() -> None:
    for name, path in _modules().items():
        leaked = _all_imported(path) & _FORBIDDEN
        assert not leaked, f"{name}.py imports sibling engine(s) it must not know: {leaked}"


def test_development_performs_no_faculty_work() -> None:
    for verb in _FORBIDDEN_VERBS:
        assert not hasattr(DevelopmentEngine, verb), f"Development must not expose {verb!r}"


def test_development_never_modifies_canonical_state() -> None:
    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        strong_reasoning(kernel.services(), 20)
        before = dev.canonical_watermark()
        for _ in range(5):
            dev.develop(ctx)
            dev.submit_for_review(ctx)
        assert dev.canonical_watermark() == before and dev.canonical_writes() == 0  # DeL13
    finally:
        teardown(kernel, rt, state, dev)


def test_artifacts_are_immutable_and_runtime_routed() -> None:
    import dataclasses

    kernel, rt, state, dev, ctx, admin = make_development()
    try:
        strong_reasoning(kernel.services(), 20)
        art = dev.develop(ctx)
        assert dataclasses.is_dataclass(art) and getattr(type(art), "__dataclass_params__").frozen  # immutable
        assert isinstance(dev._review, RuntimeReviewPort)         # noqa: SLF001 - review via runtime
        assert isinstance(dev._state, CognitiveStateManager)      # noqa: SLF001 - state via manager (read-only)
        assert isinstance(dev, ExecutableEngine) and isinstance(dev, CognitiveEngine)
        assert "development" in rt._orchestrator.names()           # noqa: SLF001 - executes via runtime
        assert "development" in kernel.engine_registry().names()   # registered with kernel
    finally:
        teardown(kernel, rt, state, dev)
