"""Architecture tests — Reasoning only reasons; it performs no other cognition."""

from __future__ import annotations

import ast
import os

import app.cognitive_kernel.engines.reasoning as rzpkg
from app.cognitive_kernel.contracts import CognitiveEngine
from app.cognitive_kernel.runtime.contracts import ExecutableEngine
from app.cognitive_kernel.state import CognitiveStateManager
from app.cognitive_kernel.engines.reasoning import ReasoningEngine
from app.cognitive_kernel.engines.reasoning.contracts import ReasoningEnginePort
from app.cognitive_kernel.engines.reasoning.pool import EnginePool
from app.cognitive_kernel.engines.reasoning.port import ReasoningWMPort

from ._rz import make_reasoning, teardown

_PKG = os.path.dirname(rzpkg.__file__)

# Engines Reasoning must never own or import. Working Memory is a permitted *read* contract.
_FORBIDDEN = {"attention", "executive", "prediction", "metacognition", "meta_cognition", "learning", "development"}
# Verbs Reasoning must never expose (it reasons; it does not act, select, or commit).
_FORBIDDEN_VERBS = ("attend", "select", "ignite", "evict", "plan", "decide", "predict", "learn", "reflect", "commit", "broadcast")


def _modules() -> dict[str, str]:
    return {
        fn[:-3]: os.path.join(_PKG, fn)
        for fn in os.listdir(_PKG)
        if fn.endswith(".py") and fn != "__init__.py"
    }


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
    assert seen == len(graph), "circular dependency among reasoning modules"


def test_contracts_is_pure_abi() -> None:
    assert _sibling_imports(os.path.join(_PKG, "contracts.py")) == set()


def test_reasoning_performs_no_other_cognition() -> None:
    for verb in _FORBIDDEN_VERBS:
        assert not hasattr(ReasoningEngine, verb), f"Reasoning must not expose {verb!r}"


def test_reasoning_knows_no_sibling_decision_engine() -> None:
    for name, path in _modules().items():
        leaked = _all_imported(path) & _FORBIDDEN
        assert not leaked, f"{name}.py references engine(s) it must not know: {leaked}"


def test_reasoning_reads_working_memory_but_never_writes_it() -> None:
    # The port is read-only: no activation/eviction/refresh/broadcast surface.
    for writer in ("ignite", "evict", "load", "refresh", "broadcast", "pin", "chunk"):
        assert not hasattr(ReasoningWMPort, writer), f"Reasoning must not be able to {writer} WM"
    # No reasoning module imports the WM *runtime write* API.
    for path in _modules().values():
        with open(path, "r", encoding="utf-8") as fh:
            assert "WorkingMemoryRuntimeApi" not in fh.read()


def test_reasoning_uses_substitutable_engines_behind_a_port() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        assert isinstance(rz._pool, EnginePool) and rz._pool.count() >= 2  # noqa: SLF001
        # every pooled engine is an instrument behind the port (ReL1: none is "the reasoner")
        for name in rz._pool.names():  # noqa: SLF001
            assert isinstance(rz._pool._engines[name], ReasoningEnginePort)  # noqa: SLF001
    finally:
        teardown(kernel, rt, state, wm, rz)


def test_state_flows_through_the_manager_and_execution_through_the_runtime() -> None:
    kernel, rt, state, wm, wm_api, rz, ctx = make_reasoning()
    try:
        assert isinstance(rz._state, CognitiveStateManager)   # noqa: SLF001 - state via the manager
        assert isinstance(rz._wm, ReasoningWMPort)            # noqa: SLF001 - conscious content via WM read port
        assert isinstance(rz, ExecutableEngine) and isinstance(rz, CognitiveEngine)
        assert "reasoning" in rt._orchestrator.names()        # noqa: SLF001 - executes via runtime
        assert "reasoning" in kernel.engine_registry().names()  # registered with kernel
    finally:
        teardown(kernel, rt, state, wm, rz)
