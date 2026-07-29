"""Architecture tests — Meta observes and evaluates; it performs no faculty's work."""

from __future__ import annotations

import ast
import os

import app.cognitive_kernel.engines.metacognition as mcpkg
from app.cognitive_kernel.contracts import CognitiveEngine
from app.cognitive_kernel.runtime.contracts import ExecutableEngine
from app.cognitive_kernel.state import CognitiveStateManager
from app.cognitive_kernel.engines.metacognition import MetaCognitionEngine
from app.cognitive_kernel.engines.metacognition.contracts import INTERVENTION_ROUTES, InterventionKind
from app.cognitive_kernel.engines.metacognition.ports import RuntimeInterventionPort

from ._mc import make_meta, teardown

_PKG = os.path.dirname(mcpkg.__file__)

# Sibling engines Meta must never import or call directly — it observes via
# infrastructure (Ledger, Health, Runtime) and routes interventions via the Runtime.
_FORBIDDEN = {"attention", "reasoning", "executive", "prediction", "learning", "development", "working_memory"}
# Faculty verbs Meta must never expose (it evaluates cognition; it never performs it).
_FORBIDDEN_VERBS = ("reason", "predict", "attend", "select", "ignite", "govern", "allocate",
                    "decide", "authorize", "learn", "forecast")


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
    assert seen == len(graph), "circular dependency among metacognition modules"


def test_contracts_is_pure_abi() -> None:
    assert _sibling_imports(os.path.join(_PKG, "contracts.py")) == set()


def test_meta_imports_no_sibling_engine() -> None:
    for name, path in _modules().items():
        leaked = _all_imported(path) & _FORBIDDEN
        assert not leaked, f"{name}.py imports sibling engine(s) it must not know: {leaked}"


def test_meta_performs_no_faculty_work() -> None:
    for verb in _FORBIDDEN_VERBS:
        assert not hasattr(MetaCognitionEngine, verb), f"Meta must not expose {verb!r}"


def test_meta_never_modifies_canonical_state() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        before = meta.canonical_watermark()
        for _ in range(5):
            meta.reflect(ctx)
            meta.constitutional_audit(ctx)
        assert meta.canonical_watermark() == before and meta.canonical_writes() == 0  # MeL9/MeL13
    finally:
        teardown(kernel, rt, state, meta)


def test_every_intervention_routes_to_executive_and_is_reversible() -> None:
    # No intervention bypasses governance (MeL2); FLAG is record-only.
    for kind, (engine, _op) in INTERVENTION_ROUTES.items():
        assert engine in ("executive", "")  # only the Executive, or record-only
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        assert isinstance(meta._intervention, RuntimeInterventionPort)  # noqa: SLF001 - runtime-routed
    finally:
        teardown(kernel, rt, state, meta)


def test_runtime_routed_and_state_read_only() -> None:
    kernel, rt, state, meta, ctx, admin = make_meta()
    try:
        assert isinstance(meta._state, CognitiveStateManager)     # noqa: SLF001 - state via manager (read-only)
        assert isinstance(meta, ExecutableEngine) and isinstance(meta, CognitiveEngine)
        assert "metacognition" in rt._orchestrator.names()         # noqa: SLF001 - executes via runtime
        assert "metacognition" in kernel.engine_registry().names()  # registered with kernel
    finally:
        teardown(kernel, rt, state, meta)
