"""Feature-flagged Cognitive Chat route (Version 1 integration slice).

A *new, additive* route — it does not touch or replace the existing chat pipeline.
When ``COGNITIVE_BRAIN_ENABLED`` is off it returns 503; when on, one conversational
turn flows end-to-end through the Cognitive Operating System:

    User -> Conversation -> Perception -> Working Memory -> Attention ->
    Reasoning -> Reasoning Port -> Ollama -> Executive -> Generation -> User

The brain runs synchronously in a worker thread; this handler only marshals I/O.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.cognitive_integration import Turn, cognitive_brain_enabled
from app.cognitive_integration.factory import get_pipeline

router = APIRouter(prefix="/cognitive-chat", tags=["Cognitive Chat (beta)"])


class CognitiveChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: str = "conv"
    mode: str = "auto"


class CognitiveChatResponse(BaseModel):
    reply: str
    authorized: bool
    decision: str
    escalated: bool
    confidence: float
    intent: str
    brain: bool = True


@router.get("/status")
async def status() -> dict:
    return {"cognitive_brain_enabled": cognitive_brain_enabled(),
            "flow": "conversation -> brain -> executive -> generation -> response"}


@router.post("/message", response_model=CognitiveChatResponse)
async def cognitive_message(req: CognitiveChatRequest) -> CognitiveChatResponse:
    if not cognitive_brain_enabled():
        raise HTTPException(status_code=503,
                            detail="Cognitive brain disabled. Set COGNITIVE_BRAIN_ENABLED=true to enable.")
    turn = Turn(message=req.message, conversation_id=req.conversation_id, mode=req.mode)

    def _run():
        return get_pipeline().handle(turn)

    result = await asyncio.to_thread(_run)  # boot + run the synchronous brain off the event loop
    return CognitiveChatResponse(
        reply=result.reply, authorized=result.authorized, decision=result.decision,
        escalated=result.escalated, confidence=result.confidence, intent=result.intent)
