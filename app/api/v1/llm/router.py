"""What the chat model can be asked to do — the profiles behind the mode picker.

Read-only and model-agnostic: it reports what ``app.llm`` resolved from code
and configuration, so the UI never hard-codes a model name or a token budget
that the server has since changed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.db.models import User
from app.llm import GENERAL, list_profiles

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/profiles")
async def get_profiles(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "default": GENERAL,
        "profiles": [p.as_public_dict() for p in list_profiles()],
    }
