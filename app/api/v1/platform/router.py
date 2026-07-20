"""
Platform-wide, cross-cutting endpoints (Phase 2.6) — not document-scoped.
Read-only; new additive surface, no existing endpoint touched.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.db.models import User
from app.document_platform.schemas import PlatformCapabilitiesOut, PlatformCapabilityOut
from app.platform.capabilities import get_capability_registry

router = APIRouter(prefix="/platform", tags=["Platform"])


@router.get("/capabilities", response_model=PlatformCapabilitiesOut)
async def list_capabilities(current_user: User = Depends(get_current_user)):
    """Every self-registered capability provider (parsers, OCR, chunker, storage)."""
    registry = get_capability_registry()
    return PlatformCapabilitiesOut(items=[
        PlatformCapabilityOut(
            name=c.name,
            category=c.category.value,
            version=c.version,
            supported_features=sorted(c.supported_features),
            limitations=sorted(c.limitations),
            status=c.status.value,
        )
        for c in registry.all()
    ])
