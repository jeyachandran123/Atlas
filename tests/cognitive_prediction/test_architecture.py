"""Architecture tests — Prediction imagines; it changes nothing and performs no faculty."""

from __future__ import annotations

import ast
import os

import app.cognitive_kernel.engines.prediction as prpkg
from app.cognitive_kernel.contracts import CognitiveEngine
from app.cognitive_kernel.runtime.contracts import ExecutableEngine
from app.cognitive_kernel.state import CognitiveStateManager
from app.cognitive_kernel.engines.prediction import PredictionEngine
from app.cognitive_kernel.engines.prediction.ports import RuntimeWMReadPort

from ._pr import driver, make_prediction, request, teardown

_PKG = os.path.dirname(prpkg.__file__)

# Sibling engines Prediction must never import or call directly — it reads State
# read-only and reaches WM only through the Runtime by name.
_FORBIDDEN = {"attention", "reasoning", "executive", "metacognition", "meta_cognition", "learning", "development"}
# Faculty verbs Prediction must never expose (it imagines; it does not act).
_FORBIDDEN_VERBS = ("reason", "attend", "select", "ignite", "decide", "authorize", "learn", "reflect", "allocate")


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
    assert seen == len(graph), "circular dependency among prediction modules"


def test_contracts_is_pure_abi() -> None:
    assert _sibling_imports(os.path.join(_PKG, "contracts.py")) == set()


def test_prediction_imports_no_sibling_engine() -> None:
    for name, path in _modules().items():
        leaked = _all_imported(path) & _FORBIDDEN
        assert not leaked, f"{name}.py imports sibling engine(s) it must not know: {leaked}"


def test_prediction_performs_no_faculty_work() -> None:
    for verb in _FORBIDDEN_VERBS:
        assert not hasattr(PredictionEngine, verb), f"Prediction must not expose {verb!r}"


def test_prediction_never_modifies_canonical_state() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        before = pred.canonical_watermark()
        for i in range(6):
            pred.forecast(request(f"r{i}", seed=i, stakes=0.9,
                                  drivers=(driver("a", 0.6, 1.0), driver("b", 0.4, -1.0))), ctx)
            pred.counterfactual(request(f"c{i}", seed=i, drivers=(driver("a", 0.6, 1.0),),
                                        interventions={"a": True}), ctx)
        assert pred.canonical_watermark() == before  # PrL8 — reality untouched
        assert pred.canonical_writes() == 0
    finally:
        teardown(kernel, rt, state, pred)


def test_branches_are_isolated_and_cleaned_up() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        pred.forecast(request("r", seed=1, drivers=(driver("d", 0.8, 1.0),)), ctx)
        assert pred._sim.open_count() == 0                          # noqa: SLF001 - destroyed after use
        assert isinstance(pred._wm, RuntimeWMReadPort)              # noqa: SLF001 - WM only via runtime
    finally:
        teardown(kernel, rt, state, pred)


def test_runtime_routed_and_state_read_only() -> None:
    kernel, rt, state, pred, ctx, admin = make_prediction()
    try:
        assert isinstance(pred._state, CognitiveStateManager)      # noqa: SLF001 - state via manager (read-only)
        assert isinstance(pred, ExecutableEngine) and isinstance(pred, CognitiveEngine)
        assert "prediction" in rt._orchestrator.names()             # noqa: SLF001 - executes via runtime
        assert "prediction" in kernel.engine_registry().names()     # registered with kernel
    finally:
        teardown(kernel, rt, state, pred)
