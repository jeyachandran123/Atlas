"""Platform Action Adapter — Executive-authorized actions become platform calls.

    Executive decision -> (adapter) -> Document / Knowledge / Workspace / Generation

The Executive never imports a platform; it authorizes. This adapter maps an authorized
action to the concrete organ, which is injected as a ``PlatformActionPort``. The chat
vertical slice does not require any platform action, but the adapter is implemented so
future integrations (Documents, Knowledge, Semantic Search, Workspace) connect through
exactly this seam — no engine or platform change needed.
"""

from __future__ import annotations

from typing import Any, Mapping

from .ports import PlatformActionPort

# Action name -> platform organ key. New organs plug in here; nothing else changes.
ACTION_ROUTES: Mapping[str, str] = {
    "search_document": "document",
    "search_knowledge": "knowledge",
    "semantic_search": "semantic",
    "search_workspace": "workspace",
    "generate_report": "generation",
}


class PlatformActionAdapter:
    def __init__(self, platforms: Mapping[str, PlatformActionPort] | None = None) -> None:
        self._platforms = dict(platforms or {})

    def available_actions(self) -> tuple[str, ...]:
        return tuple(sorted(ACTION_ROUTES))

    def dispatch(self, action: str, params: Mapping[str, Any], context: Any) -> dict[str, Any]:
        organ = ACTION_ROUTES.get(action)
        if organ is None:
            return {"executed": False, "reason": f"unknown action {action!r}"}
        platform = self._platforms.get(organ)
        if platform is None:
            # The organ exists in the routing map but is not wired in this session.
            return {"executed": False, "action": action, "organ": organ, "reason": "organ not wired"}
        result = platform.execute(action, dict(params))
        return {"executed": True, "action": action, "organ": organ, "result": result}
