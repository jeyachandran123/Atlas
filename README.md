# AI Coding Assistant

A local-first AI coding assistant that understands large codebases. Built to compete with Cursor, Claude Code, and GitHub Copilot — running entirely on your own infrastructure.

## What it does

- Indexes repositories with 100k+ files using AST-aware chunking
- Answers questions about your code using semantic search + retrieval-augmented generation
- Generates code, fixes bugs, writes tests — all grounded in your actual codebase
- Runs 100% locally via Ollama — no data leaves your server

## Quick Start

### Prerequisites

- Docker + Docker Compose
- 16GB+ RAM (32GB recommended)
- Optional: NVIDIA GPU for faster inference

### 1. Clone and configure

```bash
git clone https://github.com/your-org/ai-coding-assistant
cd ai-coding-assistant
cp .env.example .env
# Edit .env — defaults work for local dev
```

### 2. Start the stack

```bash
docker compose up -d
```

### 3. Pull AI models (first time only)

```bash
docker compose exec ollama ollama pull qwen2.5-coder:7b    # code generation
docker compose exec ollama ollama pull nomic-embed-text    # embeddings
```

### 4. Initialize the database

```bash
docker compose exec api alembic upgrade head
```

### 5. Create your first user

```bash
# Register via API
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "yourpassword", "org_id": "your-org-id"}'
```

### 6. Connect a repository and start chatting

Open http://localhost:8000/docs for the interactive API documentation.

## Services

| Service | URL | Purpose |
|---------|-----|---------|
| API | http://localhost:8000 | FastAPI application |
| API Docs | http://localhost:8000/docs | Swagger UI (dev only) |
| Grafana | http://localhost:3001 | Metrics dashboard (admin/admin) |
| Jaeger | http://localhost:16686 | Distributed traces |
| ChromaDB | http://localhost:8001 | Vector database |
| Prometheus | http://localhost:9090 | Raw metrics |

## Architecture

```
User Query
  → FastAPI API (auth, rate limiting, request ID)
  → LangGraph Orchestrator
      ┌──────────────────────────────────────────┐
      │  Tool Loop (max 5 iterations)           │
      │    → retrieve_context (ChromaDB search) │
      │    → plan_tools (LLM decides tools)     │
      │    → execute_tools (file, search, git)  │
      │    → coding_agent (Ollama response)     │
      │    → should_continue? (loop or finish)  │
      └──────────────────────────────────────────┘
  → Streaming response via SSE
```

**Tool-Use Loop (V1.1):**
- Agent can now call tools autonomously
- Available tools: read_file, write_file, search_code, git_diff, run_command
- LLM plans which tools to call based on user request
- Tools execute sequentially (later tools can use earlier results)
- Max 5 iterations to prevent infinite loops
- Tool failures don't crash the pipeline - agent adapts

**Memory System (V1.1):**
- Session memory: Last 20 messages in Redis, 24h TTL
- Long-term memory: Important facts in Redis (V1) / MSSQL+ChromaDB (V2)
- Automatic fact extraction from conversations
- Memory types: preference, fact, pattern, issue
- Importance scoring and access tracking
- Semantic search and filtering (V2)

**Repository indexing** runs in a background worker:

```
Git repo → Scanner (SHA256 hash) → AST Chunker (tree-sitter)
        → Embedder (nomic-embed-text) → ChromaDB + MSSQL
```

## Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Agent framework | LangGraph | Explicit state graph, loops, conditional edges |
| Chunking | AST-aware (tree-sitter) | 30-40% better retrieval vs text chunking |
| Vector DB | ChromaDB → Qdrant | Zero-config for V1; abstract interface for migration |
| Memory | Session (Redis) + Long-term (Redis→DB) | Fast access, automatic consolidation, persistent learning |
| Agent count | 1 in V1 | Avoid coordination overhead; split only when measured benefit |

## Roadmap

**V1** (current): Single developer, one agent, semantic search, streaming chat

**V2**: Team support, ReviewAgent, long-term memory, Git webhooks, JetBrains plugin

**V3**: Qdrant migration, autonomous debugging agent, enterprise SSO, Kubernetes

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add features, agents, and language support.

```bash
# Run tests
pytest

# Quality checks
ruff check app tests && black --check app tests && mypy app --ignore-missing-imports
```

## License

MIT
