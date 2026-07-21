"""
FastAPI application entry point.

Wires together:
- Middleware (auth, metrics, request ID, CORS, rate limiting)
- API routers (auth, repositories, indexing, chat, admin)
- Startup/shutdown lifecycle (DB, Redis, Ollama, ChromaDB, orchestrator)
- Exception handlers (domain exceptions → HTTP responses)
- Prometheus metrics endpoint
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.agents.orchestrator import AgentOrchestrator, get_orchestrator
from app.api.v1.admin.router import router as admin_router
from app.api.v1.auth.router import router as auth_router
from app.api.v1.chat.router import router as chat_router
from app.api.v1.conversations.router import router as conversations_router
from app.api.v1.documents.router import router as documents_router
from app.api.v1.files.router import router as files_router
from app.api.v1.platform.router import router as platform_router
from app.api.v1.git.router import router as git_router
from app.api.v1.indexing.router import router as indexing_router
from app.api.v1.repositories.router import router as repos_router
from app.config import get_settings
from app.database import close_engine, get_engine
from app.observability import configure_logging, metrics_middleware, setup_opentelemetry
from app.rate_limit import limiter
from app.redis_client import close_redis, get_redis
from app.shared.exceptions import AIAssistantError

cfg = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan manager.
    Everything before `yield` runs on startup.
    Everything after `yield` runs on shutdown.
    """
    from loguru import logger

    configure_logging()
    logger.info(f"Starting AI Coding Assistant [{cfg.app_env}]")

    # Initialize Firebase Admin SDK
    from app.firebase_admin import initialize_firebase
    try:
        initialize_firebase()
    except Exception as e:
        logger.error(f"Failed to initialize Firebase: {e}")
        logger.warning("Firebase authentication will not be available")

    # Verify DB engine can connect (doesn't create tables — use Alembic)
    engine = get_engine()
    logger.info("Database engine ready")

    # Verify Redis
    r = get_redis()
    await r.ping()
    logger.info("Redis connection verified")

    # Build the ChromaDB-backed orchestrator
    try:
        from app.vector_store.chroma_client import get_chroma_store
        store = await get_chroma_store()
        orchestrator = get_orchestrator(vector_store=store)
        logger.info("Agent orchestrator ready (ChromaDB connected)")
    except Exception as e:
        logger.warning(f"ChromaDB unavailable: {e} — orchestrator running without retrieval")
        orchestrator = get_orchestrator(vector_store=None)

    app.state.orchestrator = orchestrator

    # Check Ollama
    from app.ollama_client import get_ollama_client
    ollama = get_ollama_client()
    available, latency_ms = await ollama.health_check()
    if available:
        logger.info(f"Ollama available (latency: {latency_ms}ms)")
    else:
        logger.warning("Ollama not available — AI responses will fail until Ollama is running")

    logger.info(f"AI Coding Assistant started on {cfg.app_host}:{cfg.app_port}")

    yield  # ← Application runs here

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down...")

    from app.ollama_client import close_ollama_client
    await close_ollama_client()
    await close_redis()
    await close_engine()

    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    """
    Application factory.
    Creates and configures the FastAPI instance.
    """
    app = FastAPI(
        title="AI Coding Assistant",
        description=(
            "Local-first AI coding assistant. "
            "Understands large codebases via semantic indexing and retrieval."
        ),
        version="1.0.0",
        docs_url="/docs" if cfg.app_debug else None,
        redoc_url="/redoc" if cfg.app_debug else None,
        openapi_url="/openapi.json" if cfg.app_debug else None,
        lifespan=lifespan,
    )

    # ── Rate limiting ─────────────────────────────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request metrics + request ID ─────────────────────────────────────────
    app.middleware("http")(metrics_middleware)

    # ── OpenTelemetry ─────────────────────────────────────────────────────────
    setup_opentelemetry(app)

    # ── Exception handlers ────────────────────────────────────────────────────
    @app.exception_handler(AIAssistantError)
    async def domain_exception_handler(
        request: Request, exc: AIAssistantError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "status": "error",
                "message": exc.message,
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        from loguru import logger
        logger.exception(f"Unhandled error: {exc}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": "An unexpected error occurred",
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    # ── Routers ───────────────────────────────────────────────────────────────
    API_PREFIX = "/api/v1"

    app.include_router(admin_router, prefix=API_PREFIX)
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(repos_router, prefix=API_PREFIX)
    app.include_router(indexing_router, prefix=API_PREFIX)
    app.include_router(chat_router, prefix=API_PREFIX)
    app.include_router(documents_router, prefix=API_PREFIX)
    app.include_router(conversations_router, prefix=API_PREFIX)
    app.include_router(files_router, prefix=API_PREFIX)
    app.include_router(platform_router, prefix=API_PREFIX)
    app.include_router(git_router, prefix=API_PREFIX)

    # Root redirect
    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {
            "service": "AI Coding Assistant",
            "version": "1.0.0",
            "docs": "/docs" if cfg.app_debug else "Disabled in production",
        }

    return app


# ── Application instance ──────────────────────────────────────────────────────
app = create_app()
