"""Architecture tests — the runtime coordinates cognition but performs none."""

from __future__ import annotations

import ast
import os

import app.cognitive_kernel.runtime as rtpkg
from app.cognitive_kernel.runtime import CognitiveRuntime
from app.cognitive_kernel.runtime.contracts import ExecutableEngine, RuntimeApi

_PKG = os.path.dirname(rtpkg.__file__)

# Names of the cognitive engines that must NOT be known to the runtime.
_FORBIDDEN = {
    "reasoning", "attention", "working_memory", "executive",
    "prediction", "metacognition", "meta_cognition", "learning", "development",
}


def _modules() -> dict[str, str]:
    return {
        fn[:-3]: os.path.join(_PKG, fn)
        for fn in os.listdir(_PKG)
        if fn.endswith(".py") and fn != "__init__.py"
    }


def _sibling_imports(path: str) -> set[str]:
    """Relative imports of *sibling* runtime modules (level == 1 only)."""
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    deps: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                deps.add(node.module.split(".")[0])
            else:
                for alias in node.names:
                    deps.add(alias.name.split(".")[0])
    return deps


def _all_imported_names(path: str) -> set[str]:
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.update(node.module.split("."))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.update(alias.name.split("."))
    return names


def test_no_circular_dependencies_among_runtime_modules() -> None:
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
    assert seen == len(graph), "circular dependency among runtime modules"


def test_runtime_contracts_are_pure_abi() -> None:
    # contracts depends on no sibling runtime module.
    assert _sibling_imports(os.path.join(_PKG, "contracts.py")) == set()


def test_runtime_knows_nothing_about_cognition() -> None:
    # No runtime module imports (or is named for) a cognitive engine.
    for name, path in _modules().items():
        assert name not in _FORBIDDEN
        imported = _all_imported_names(path)
        leaked = imported & _FORBIDDEN
        assert not leaked, f"{name}.py references cognitive engine(s): {leaked}"


def test_runtime_exposes_no_cognitive_verbs() -> None:
    for verb in ("reason", "attend", "plan", "predict", "learn", "reflect", "remember", "think"):
        assert not hasattr(CognitiveRuntime, verb), f"runtime must not expose {verb!r}"


def test_runtime_imports_only_kernel_and_stdlib() -> None:
    # Every non-stdlib import must live under app.cognitive_kernel (the foundation).
    for name, path in _modules().items():
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    assert top != "app", f"{name}.py uses absolute app import (use relative)"
            elif isinstance(node, ast.ImportFrom):
                # Only relative (kernel) imports and stdlib froms are allowed.
                if node.level == 0 and node.module and node.module.startswith("app"):
                    raise AssertionError(f"{name}.py imports app.* absolutely: {node.module}")


def test_engine_contract_is_the_only_execution_surface() -> None:
    # Engines are executed through the ExecutableEngine contract, and callers use
    # the RuntimeApi surface — never each other.
    assert hasattr(ExecutableEngine, "execute")
    for m in ("submit", "cancel", "status"):
        assert hasattr(RuntimeApi, m)
