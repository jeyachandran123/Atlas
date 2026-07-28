"""Working Memory API — routes every operation through the Cognitive Runtime.

Future engines (Attention, Reasoning, Executive, …) use this facade. It never
calls the engine directly; it submits a runtime :class:`ExecutionRequest`, so
every Working Memory operation flows through the runtime pipeline (context,
budget, state machine, events, ledger, metrics).
"""

from __future__ import annotations

from typing import Any

from ...contracts import ExecutionContext
from ...runtime import ExecutionRequest


class WorkingMemoryRuntimeApi:
    def __init__(self, runtime, engine_name: str = "working_memory") -> None:
        self._rt = runtime
        self._name = engine_name

    def _run(self, operation: str, payload: dict[str, Any], context: ExecutionContext) -> Any:
        handle = self._rt.submit(
            ExecutionRequest(
                engine=self._name, operation=operation, payload=payload,
                correlation_id=context.correlation_id, security=context.security,
            )
        )
        self._rt.drain()
        result = handle.result()
        if result.error:
            raise RuntimeError(f"WM operation {operation!r} failed: {result.error}")
        return result.value

    # Attention hook — decides what enters; WM only activates it.
    def ignite(self, target: str, context: ExecutionContext, **kw: Any) -> str:
        return self._run("load", {"target": target, **kw}, context)

    def load(self, target: str, context: ExecutionContext, **kw: Any) -> str:
        return self._run("load", {"target": target, **kw}, context)

    def refresh(self, ref: str, context: ExecutionContext, **kw: Any) -> None:
        self._run("refresh", {"ref": ref, **kw}, context)

    def evict(self, ref: str, context: ExecutionContext) -> None:
        self._run("evict", {"ref": ref}, context)

    def pin(self, ref: str, context: ExecutionContext, pinned: bool = True) -> None:
        self._run("pin", {"ref": ref, "pinned": pinned}, context)

    def chunk(self, members: list[str], context: ExecutionContext, **kw: Any) -> str:
        return self._run("chunk", {"members": members, **kw}, context)

    def expire(self, context: ExecutionContext, **kw: Any) -> int:
        return self._run("expire", {**kw}, context)

    def broadcast(self, context: ExecutionContext, workspace: str | None = None) -> list[str]:
        return self._run("broadcast", {"workspace": workspace}, context)

    def open_workspace(self, kind: str, context: ExecutionContext, **kw: Any) -> str:
        return self._run("open_workspace", {"kind": kind, **kw}, context)

    def close_workspace(self, workspace: str, context: ExecutionContext) -> int:
        return self._run("close_workspace", {"workspace": workspace}, context)

    def branch_simulation(self, base: str, context: ExecutionContext) -> str:
        return self._run("branch_simulation", {"base": base}, context)

    def discard_simulation(self, workspace: str, context: ExecutionContext) -> int:
        return self._run("discard_simulation", {"workspace": workspace}, context)
