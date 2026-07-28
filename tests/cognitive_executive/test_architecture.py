"""Architecture tests — the Executive governs; it performs no faculty's work."""

from __future__ import annotations

import ast
import os

import app.cognitive_kernel.engines.executive as expkg
from app.cognitive_kernel.contracts import CognitiveEngine
from app.cognitive_kernel.runtime.contracts import ExecutableEngine
from app.cognitive_kernel.state import CognitiveStateManager
from app.cognitive_kernel.engines.executive import ExecutiveEngine, Policy, PolicyEffect, PolicyFamily
from app.cognitive_kernel.engines.executive.ports import RuntimeAttentionPort, RuntimeReasoningPort

from ._ex import make_executive, proposal, teardown

_PKG = os.path.dirname(expkg.__file__)

# Sibling engines the Executive must never import or call directly — it coordinates
# them ONLY through the Runtime by name (ExL8: no direct engine-to-engine communication).
_FORBIDDEN = {
    "attention", "reasoning", "working_memory", "prediction",
    "metacognition", "meta_cognition", "learning", "development",
}
# Faculty verbs the Executive must never expose (it governs; it does not perform).
_FORBIDDEN_VERBS = ("reason", "attend", "select", "ignite", "predict", "learn", "reflect", "infer", "simulate")


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
    assert seen == len(graph), "circular dependency among executive modules"


def test_contracts_is_pure_abi() -> None:
    assert _sibling_imports(os.path.join(_PKG, "contracts.py")) == set()


def test_executive_imports_no_sibling_engine() -> None:
    for name, path in _modules().items():
        leaked = _all_imported(path) & _FORBIDDEN
        assert not leaked, f"{name}.py imports sibling engine(s) it must not know: {leaked}"


def test_executive_performs_no_faculty_work() -> None:
    for verb in _FORBIDDEN_VERBS:
        assert not hasattr(ExecutiveEngine, verb), f"Executive must not expose {verb!r}"


def test_coordination_is_runtime_routed_by_name() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        # The control ports hold the runtime and an engine *name* — never an engine reference.
        assert isinstance(ex._reasoning_port, RuntimeReasoningPort)   # noqa: SLF001
        assert isinstance(ex._attention_port, RuntimeAttentionPort)   # noqa: SLF001
        assert ex._reasoning_port._name == "reasoning"                # noqa: SLF001
        assert ex._attention_port._name == "attention"                # noqa: SLF001
    finally:
        teardown(kernel, rt, state, ex)


def test_state_via_manager_and_execution_via_runtime() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        assert isinstance(ex._state, CognitiveStateManager)          # noqa: SLF001 - state via manager
        assert isinstance(ex, ExecutableEngine) and isinstance(ex, CognitiveEngine)
        assert "executive" in rt._orchestrator.names()                # noqa: SLF001 - executes via runtime
        assert "executive" in kernel.engine_registry().names()        # registered with kernel
    finally:
        teardown(kernel, rt, state, ex)


def test_constitutional_policies_are_enforced() -> None:
    kernel, rt, state, ex, ctx, admin = make_executive()
    try:
        families = {p.family for p in ex._policy.policies()}          # noqa: SLF001
        assert PolicyFamily.SAFETY in families and PolicyFamily.IDENTITY in families
        # An absolute safety DENY cannot be overridden by any confidence.
        ex.enact_policy(admin, Policy("blk", PolicyFamily.SAFETY, "no_x", PolicyEffect.DENY,
                                      predicate={"statement_contains": "forbidden"}))
        out = ex.govern(proposal("p", "do forbidden thing", 1.0, kind="action"), ctx)
        assert not out.authorized and out.decision.kind.value == "reject"  # ExL7
    finally:
        teardown(kernel, rt, state, ex)
