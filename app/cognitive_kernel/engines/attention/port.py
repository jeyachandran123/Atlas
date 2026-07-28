"""Working-Memory port — the only surface Attention uses to touch WM.

Reads use WM's public read methods; writes are routed through the Working Memory
Runtime API (runtime-mediated), so Attention never communicates *directly* with
WM's internals and never bypasses infrastructure (AL16: it gates WM, it does not
own it).
"""

from __future__ import annotations

from typing import Any, Sequence

from ..working_memory import WorkingMemoryEngine
from ..working_memory.api import WorkingMemoryRuntimeApi


class AttentionWMPort:
    def __init__(self, wm_engine: WorkingMemoryEngine, wm_api: WorkingMemoryRuntimeApi) -> None:
        self._wm = wm_engine        # public read contract
        self._api = wm_api          # runtime-routed write contract

    # reads (public contract) -------------------------------------------- #
    def contents(self, workspace: str | None = None) -> Sequence[Any]:
        return self._wm.contents(workspace)

    def read_focus(self, workspace: str | None = None) -> Sequence[Any]:
        return self._wm.read_focus(workspace)

    # writes (routed through the runtime) -------------------------------- #
    def ignite(self, target: str, context: Any, **kw: Any) -> str:
        return self._api.ignite(target, context, **kw)

    def refresh(self, ref: str, context: Any, **kw: Any) -> None:
        self._api.refresh(ref, context, **kw)

    def evict(self, ref: str, context: Any) -> None:
        self._api.evict(ref, context)

    def broadcast(self, context: Any, workspace: str | None = None) -> Any:
        return self._api.broadcast(context, workspace)
