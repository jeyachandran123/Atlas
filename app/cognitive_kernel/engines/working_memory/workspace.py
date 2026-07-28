"""Workspace registry — ephemeral WM contexts (goal/task/belief/…/simulation).

Workspaces are ephemeral cognitive contexts; the durable membership lives in the
Cognitive State (R4). The registry is reconstructable from R4 (§5.6).
"""

from __future__ import annotations

import threading
import uuid

from .contracts import WorkspaceInfo, WorkspaceKind
from .errors import UnknownWorkspaceError


class WorkspaceRegistry:
    def __init__(self) -> None:
        self._workspaces: dict[str, WorkspaceInfo] = {}
        self._lock = threading.RLock()

    def create(self, kind: WorkspaceKind, parent: str | None, isolated: bool, seq: int) -> str:
        wsid = f"ws-{kind.value}-{uuid.uuid4().hex[:8]}"
        return self.create_with_id(wsid, kind, parent, isolated, seq)

    def create_with_id(self, wsid: str, kind: WorkspaceKind, parent: str | None, isolated: bool, seq: int) -> str:
        with self._lock:
            self._workspaces[wsid] = WorkspaceInfo(wsid, kind, parent, isolated, seq)
            return wsid

    def get(self, wsid: str) -> WorkspaceInfo:
        with self._lock:
            if wsid not in self._workspaces:
                raise UnknownWorkspaceError(f"Unknown workspace: {wsid}")
            return self._workspaces[wsid]

    def exists(self, wsid: str) -> bool:
        with self._lock:
            return wsid in self._workspaces

    def remove(self, wsid: str) -> None:
        with self._lock:
            self._workspaces.pop(wsid, None)

    def all(self) -> tuple[WorkspaceInfo, ...]:
        with self._lock:
            return tuple(self._workspaces.values())

    def count(self) -> int:
        with self._lock:
            return len(self._workspaces)
