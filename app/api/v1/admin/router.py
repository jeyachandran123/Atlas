"""
Admin API — system health, model management, metrics endpoint.

Endpoints:
  GET /api/v1/admin/health          → system health (public)
  GET /api/v1/admin/health/detailed → detailed health (admin only)
  GET /api/v1/admin/metrics         → Prometheus metrics
  GET /api/v1/admin/models          → available Ollama models
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.auth import require_admin
from app.db.models import User
from app.ollama_client import get_ollama_client
from app.redis_client import get_redis
from app.observability import ollama_available

router = APIRouter(prefix="/admin", tags=["Administration"])


@router.get("/health")
async def health_check() -> dict:
    """
    Basic health check — always public.
    Used by load balancers and uptime monitors.
    Returns 200 if the API process is alive.
    """
    return {"status": "ok", "service": "ai-coding-assistant"}


@router.get("/health/detailed")
async def detailed_health(
    current_user: User = Depends(require_admin),
) -> dict:
    """Detailed health — checks all dependencies. Admin only."""
    services: dict[str, dict] = {}

    # Check Ollama
    ollama = get_ollama_client()
    available, latency_ms = await ollama.health_check()
    services["ollama"] = {
        "status": "online" if available else "offline",
        "latency_ms": latency_ms,
        "model": (await ollama.list_models())[0] if available else None,
    }
    ollama_available.set(1 if available else 0)

    # Check Redis
    try:
        r = get_redis()
        await r.ping()
        services["redis"] = {"status": "online"}
    except Exception as e:
        services["redis"] = {"status": "offline", "error": str(e)}

    # Check ChromaDB
    try:
        from app.vector_store.chroma_client import get_chroma_store
        store = await get_chroma_store()
        services["chromadb"] = {"status": "online"}
    except Exception as e:
        services["chromadb"] = {"status": "offline", "error": str(e)}

    all_ok = all(s.get("status") == "online" for s in services.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "services": services,
    }


@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus metrics endpoint."""
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)


@router.get("/models")
async def list_models(
    current_user: User = Depends(require_admin),
) -> dict:
    """List locally available Ollama models."""
    ollama = get_ollama_client()
    models = await ollama.list_models()
    return {"models": models, "count": len(models)}
