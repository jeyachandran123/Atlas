"""Architecture tests — Attention selects; it performs no other cognition."""

from __future__ import annotations

import ast
import os

import app.cognitive_kernel.engines.attention as atpkg
from app.cognitive_kernel.contracts import CognitiveEngine
from app.cognitive_kernel.runtime.contracts import ExecutableEngine
from app.cognitive_kernel.state import CognitiveStateManager
from app.cognitive_kernel.engines.attention import AttentionEngine
from app.cognitive_kernel.engines.attention.port import AttentionWMPort
from app.cognitive_kernel.engines.attention.salience import SalienceEngine
from app.cognitive_kernel.engines.working_memory.api import WorkingMemoryRuntimeApi

from ._at import make_attention, teardown

_PKG = os.path.dirname(atpkg.__file__)

# Engines Attention must never own or import (Working Memory is a permitted contract).
_FORBIDDEN = {
    "reasoning", "executive", "prediction",
    "metacognition", "meta_cognition", "learning", "development",
}
# Cognitive verbs Attention must never expose (it selects; it does not think).
_FORBIDDEN_VERBS = ("reason", "plan", "predict", "learn", "reflect", "decide", "infer", "simulate")


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
    assert seen == len(graph), "circular dependency among attention modules"


def test_contracts_is_pure_abi() -> None:
    assert _sibling_imports(os.path.join(_PKG, "contracts.py")) == set()


def test_attention_performs_no_other_cognition() -> None:
    for verb in _FORBIDDEN_VERBS:
        assert not hasattr(AttentionEngine, verb), f"Attention must not expose {verb!r}"


def test_attention_knows_no_other_engine() -> None:
    for name, path in _modules().items():
        leaked = _all_imported(path) & _FORBIDDEN
        assert not leaked, f"{name}.py references engine(s) it must not know: {leaked}"


def test_working_memory_is_updated_only_through_public_runtime_contract() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention()
    try:
        assert isinstance(att._wm, AttentionWMPort)          # noqa: SLF001 - WM only via the port
        assert isinstance(att._wm._api, WorkingMemoryRuntimeApi)  # noqa: SLF001 - writes routed via runtime
        # Attention has no direct WM-mutation method of its own.
        assert not hasattr(AttentionEngine, "load")
        assert not hasattr(AttentionEngine, "evict_wm")
    finally:
        teardown(kernel, rt, sm, wm, att)


def test_selection_uses_only_salience_and_flows_through_infrastructure() -> None:
    kernel, rt, sm, wm, att, ctx = make_attention()
    try:
        assert isinstance(att._salience, SalienceEngine)     # noqa: SLF001 - salience-only selection
        assert isinstance(att._state, CognitiveStateManager)  # noqa: SLF001 - state via the manager
        assert isinstance(att, ExecutableEngine) and isinstance(att, CognitiveEngine)
        assert "attention" in rt._orchestrator.names()        # noqa: SLF001 - executes via runtime
        assert "attention" in kernel.engine_registry().names()  # registered with kernel
    finally:
        teardown(kernel, rt, sm, wm, att)
