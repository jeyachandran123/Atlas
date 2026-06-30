# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Builder
# Installs Python dependencies into an isolated venv.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Runtime
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="AI Coding Assistant" \
      org.opencontainers.image.description="Local-first AI coding assistant" \
      org.opencontainers.image.version="1.0.0"

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Non-root user
RUN useradd --create-home --shell /bin/bash --uid 1001 appuser

WORKDIR /app
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser pyproject.toml ./
COPY --chown=appuser:appuser alembic.ini ./

USER appuser

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/admin/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--loop", "asyncio"]

# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — Worker (same dependencies, different CMD)
# ─────────────────────────────────────────────────────────────────────────────
FROM runtime AS worker

CMD ["python", "-m", "app.workers.index_worker"]

# ─────────────────────────────────────────────────────────────────────────────
# Stage 4 — Sandbox (for terminal tool execution)
# Minimal image with common dev tools. No curl, no wget after install.
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS sandbox

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        make \
        nodejs \
        npm \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest pytest-cov ruff black mypy

# Minimal non-root user
RUN useradd --no-create-home --shell /bin/sh --uid 2001 sandbox

USER sandbox
WORKDIR /workspace
