"""Architecture tests — the State Manager owns state, performs no cognition."""

from __future__ import annotations

import ast
import os

import app.cognitive_kernel.state as stpkg
from app.cognitive_kernel.state import CognitiveStateManager

_PKG = os.path.dirname(stpkg.__file__)

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
    assert seen == len(graph), "circular dependency among state modules"


def test_contracts_is_pure_abi() -> None:
    assert _sibling_imports(os.path.join(_PKG, "contracts.py")) == set()


def test_state_manager_performs_no_cognition() -> None:
    for verb in (
        "reason", "attend", "plan", "predict", "learn", "reflect", "decide", "simulate", "think", "infer"
    ):
        assert not hasattr(CognitiveStateManager, verb), f"state manager must not expose {verb!r}"


def test_state_knows_nothing_about_engines() -> None:
    for name, path in _modules().items():
        assert name not in _FORBIDDEN
        leaked = _all_imported(path) & _FORBIDDEN
        assert not leaked, f"{name}.py references cognitive engine(s): {leaked}"


def test_imports_only_kernel_and_stdlib() -> None:
    for name, path in _modules().items():
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] != "app", f"{name}.py: use relative kernel imports"
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module and node.module.startswith("app"):
                    raise AssertionError(f"{name}.py imports app.* absolutely")


def test_engines_read_and_write_only_through_the_contract() -> None:
    # The only mutation path is a transaction; the only read path is get/query.
    for m in ("begin_transaction", "get", "query", "all_current", "snapshot"):
        assert hasattr(CognitiveStateManager, m)
    # There is no public method that writes state outside a transaction/rollback/merge.
    assert not hasattr(CognitiveStateManager, "set")
    assert not hasattr(CognitiveStateManager, "put")
    assert not hasattr(CognitiveStateManager, "delete")
