"""
Streaming Engine (Objective 12) — frames (event, payload) tuples into SSE
wire format. Knows nothing about reasoning, retrieval, or providers; any
LLM provider that yields text chunks streams through unchanged.

Wire protocol:
    event: meta       {turn_id, conversation_id, intent, correlation_id}
    event: token      {text}                       (repeated)
    event: citations  {citations: [...], grounded, grounding_score}
    event: done       {status, metrics}
    event: error      {message}
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator


class StreamingEngine:
    @staticmethod
    def format(event: str, payload: dict[str, Any]) -> str:
        return f"event: {event}\ndata: {json.dumps(payload)}\n\n"

    async def sse(
        self, events: AsyncIterator[tuple[str, dict[str, Any]]],
    ) -> AsyncIterator[str]:
        async for event, payload in events:
            yield self.format(event, payload)
