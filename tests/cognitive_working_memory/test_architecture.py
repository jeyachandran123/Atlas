"""Architecture tests — Working Memory owns the workspace, performs no cognition."""

from __future__ import annotations

import ast
import os

import app.cognitive_kernel.engines.working_memory as wmpkg
from app.cognitive_kernel.contracts import CognitiveEngine
from app.cognitive_kernel.runtime.contracts import ExecutableEngine
from app.cognitive_kernel.state import CognitiveStateManager
from app.cognitive_kernel.engines.working_memory import WorkingMemoryEngine
from app.cognitive_kernel.engines.working_memory.refs import build_payload
from app.cognitive_kernel.engines.working_memory.contracts import Zone

from ._wm import make_targets, make_wm, teardown

_PKG = os.path.dirname(wmpkg.__file__)

# Engines the WM must never own or import.
_FORBIDDEN = {
    "reasoning", "attention", "executive", "prediction",
    "metacognition", "meta_cognition", "learning", "development",
}
# Cognitive verbs the WM must never expose (it is a workspace, not a thinker).
_FORBIDDEN_VERBS = ("reason", "attend", "select", "plan", "predict", "learn", "reflect", "decide", "infer")


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
    assert seen == len(graph), "circular dependency among working-memory modules"


def test_contracts_is_pure_abi() -> None:
    assert _sibling_imports(os.path.join(_PKG, "contracts.py")) == set()


def test_wm_owns_no_cognition() -> None:
    for verb in _FORBIDDEN_VERBS:
        assert not hasattr(WorkingMemoryEngine, verb), f"WM must not expose {verb!r}"


def test_wm_imports_no_sibling_engine() -> None:
    for name, path in _modules().items():
        leaked = _all_imported(path) & _FORBIDDEN
        assert not leaked, f"{name}.py references engine(s) it must not know: {leaked}"


def test_wm_stores_only_references() -> None:
    payload = build_payload(target="target-handle", workspace="ws", zone=Zone.FOCUS, base_activation=1.0, loaded_seq=0)
    assert payload["target"] == "target-handle"           # a handle, not content
    assert set(payload) == {
        "target", "workspace", "zone", "base_activation", "loaded_seq", "pinned", "chunk_of", "is_chunk", "provenance"
    }  # only reference metadata; no copied object content


def test_wm_executes_through_runtime_and_registers_with_kernel() -> None:
    kernel, rt, sm, wm, ctx = make_wm()
    try:
        assert isinstance(wm, ExecutableEngine)   # runtime execution contract
        assert isinstance(wm, CognitiveEngine)     # kernel lifecycle contract
        assert "working_memory" in rt._orchestrator.names()  # noqa: SLF001 - registered with runtime
        assert "working_memory" in kernel.engine_registry().names()  # registered with kernel
    finally:
        teardown(kernel, rt, sm, wm)


def test_wm_state_mutations_flow_through_the_state_manager() -> None:
    kernel, rt, sm, wm, ctx = make_wm()
    try:
        assert isinstance(wm._state, CognitiveStateManager)  # noqa: SLF001
        # WM keeps no private store of cognitive objects — all refs are in State.
        for t in make_targets(sm, ctx, 3):
            wm.load(t, ctx)
        from app.cognitive_kernel.state import ObjectStatus, Region
        from app.cognitive_kernel.engines.working_memory.refs import WM_REF_TYPE

        in_state = sm.query(region=Region.R4_WORKING_MEMORY, type=WM_REF_TYPE, status=ObjectStatus.ACTIVE)
        assert len(in_state) == len(wm.contents(wm._active))  # noqa: SLF001 - engine reflects State exactly
    finally:
        teardown(kernel, rt, sm, wm)
