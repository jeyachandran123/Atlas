#!/bin/bash
# First-time setup script for AI Coding Assistant
set -e

echo "AI Coding Assistant — Setup"
echo "═══════════════════════════"

# Check dependencies
command -v docker >/dev/null 2>&1 || { echo "Docker is required. Install from https://docker.com"; exit 1; }
command -v docker-compose >/dev/null 2>&1 || command -v "docker compose" >/dev/null 2>&1 || { echo "Docker Compose is required."; exit 1; }

# Copy .env if not present
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example — review before starting in production"
fi

# Start infrastructure
echo ""
echo "Starting services..."
docker compose up -d mssql redis chromadb ollama

echo "Waiting for MSSQL to be ready (30s)..."
sleep 30

# Run migrations
echo "Running database migrations..."
docker compose run --rm api alembic upgrade head

# Pull Ollama models
echo ""
echo "Pulling Ollama models (this may take several minutes)..."
docker compose exec -T ollama ollama pull qwen2.5-coder:7b || echo "Model pull failed — run manually: docker compose exec ollama ollama pull qwen2.5-coder:7b"
docker compose exec -T ollama ollama pull nomic-embed-text || echo "Model pull failed — run manually: docker compose exec ollama ollama pull nomic-embed-text"

# Start remaining services
echo ""
echo "Starting API and worker..."
docker compose up -d

echo ""
echo "Setup complete!"
echo ""
echo "  API docs:  http://localhost:8000/docs"
echo "  Grafana:   http://localhost:3001  (admin/admin)"
echo "  Jaeger:    http://localhost:16686"
echo ""
echo "Next steps:"
echo "  1. Register a user:    POST http://localhost:8000/api/v1/auth/register"
echo "  2. Get a token:        POST http://localhost:8000/api/v1/auth/login"
echo "  3. Connect a repo:     POST http://localhost:8000/api/v1/repositories"
echo "  4. Chat:               POST http://localhost:8000/api/v1/chat/message"
