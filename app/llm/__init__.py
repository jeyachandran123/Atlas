"""The application's chat model: one gateway, named profiles.

    from app.llm import get_chat_gateway

    result = await get_chat_gateway().complete(user="…", profile="reasoning")
    result.text        # the answer
    result.reasoning   # the thinking, kept apart from the answer

Vision has its own adapters (``app.adapters.document_vlm``) and embeddings stay
local; everything that generates text comes through here.
"""

from app.llm.gateway import (
    ChatGateway,
    ChatResult,
    LLMGatewayError,
    StreamEvent,
    get_chat_gateway,
    reset_chat_gateway,
)
from app.llm.profiles import (
    AGENT_PLANNING,
    CODEGEN,
    CODING,
    DOCUMENT,
    FAST,
    GENERAL,
    MATH,
    PUBLIC_PROFILES,
    REASONING,
    ChatProfile,
    list_profiles,
    profile_for_mode,
    resolve_profile,
)

__all__ = [
    "AGENT_PLANNING", "CODEGEN", "CODING", "DOCUMENT", "FAST", "GENERAL", "MATH",
    "PUBLIC_PROFILES", "REASONING",
    "ChatGateway", "ChatProfile", "ChatResult", "LLMGatewayError", "StreamEvent",
    "get_chat_gateway", "list_profiles", "profile_for_mode", "reset_chat_gateway",
    "resolve_profile",
]
