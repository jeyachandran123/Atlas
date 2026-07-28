"""Working-Memory read port — the ONLY surface Reasoning uses to touch WM.

Reasoning consumes conscious content (ReL12) through WM's *public read contract*
and nothing else. There are no write methods here: Reasoning never activates,
evicts, refreshes, or otherwise owns Working Memory (that is Attention's and WM's
authority). This read-only boundary is what the architecture tests verify.
"""

from __future__ import annotations

from typing import Any, Sequence

from ..working_memory import WorkingMemoryEngine


class ReasoningWMPort:
    def __init__(self, wm_engine: WorkingMemoryEngine) -> None:
        self._wm = wm_engine  # public read contract only

    def read_focus(self, workspace: str | None = None) -> Sequence[Any]:
        return self._wm.read_focus(workspace)

    def contents(self, workspace: str | None = None) -> Sequence[Any]:
        return self._wm.contents(workspace)
