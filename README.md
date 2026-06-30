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
  → LangGraph Orchestrator (V1.2)
      ┌──────────────────────────────────────────────────┐
      │ 1. route_intent (keyword-based)              │
      │ 2. load_memory (session + long-term)         │
      │ 3. retrieve_context (ChromaDB semantic search)│
      │ 4. plan_tools (LLM decides what tools needed) │
      └──────────────────────────────────────────────────┘
            ↓
      ┌──────────────────────────────────────────────────┐
      │ Tool Loop (max 5 iterations)                 │
      │   → execute_tools (read, write, search, git)│
      │   → coding_agent (Ollama generates response) │
      │   → should_continue? (needs more tools?)    │
      │   └── loops back to plan_tools if needed     │
      └──────────────────────────────────────────────────┘
            ↓
      ┌──────────────────────────────────────────────────┐
      │ Review Loop (fix/test intents, max 2 cycles) │
      │   → review_agent (adversarial validation)   │
      │   → check_revision (approved vs needs work)  │
      │   └── loops to plan_tools if NEEDS_REVISION │
      └──────────────────────────────────────────────────┘
            ↓
      finalise (save to memory)
  → Streaming response via SSE
```

**Tool-Use Loop (V1.2):**
- Agent autonomously calls tools based on user request
- Available tools: read_file, write_file, search_code, git_diff, run_command
- LLM planner decides which tools to call and in what order
- Tools execute sequentially (later tools can use earlier results)
- Max 5 iterations to prevent infinite loops
- Tool failures don't crash the pipeline — agent adapts
- Agent can request more tools mid-conversation

**Review Loop (V1.2):**
- Triggered automatically for fix/test/review intents or file modifications
- Adversarial ReviewAgent validates code quality, security, correctness
- Can request up to 2 revisions before finalizing
- Prevents bugs from reaching users
- Skipped for explain/search intents (no code changes)

**Memory System (V1.2):**
- Session memory: Last 20 messages in Redis, 24h TTL
- Long-term memory: Important facts in PostgreSQL + ChromaDB semantic search
- Automatic fact extraction from conversations
- Memory types: preference, fact, pattern, issue
- Importance scoring and access tracking
- Consolidated into long-term storage asynchronously

**Repository indexing** runs in a background worker:

```
Git repo → Scanner (SHA256 hash) → AST Chunker (tree-sitter)
        → Embedder (nomic-embed-text) → ChromaDB + PostgreSQL
```

## Key Design Decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Agent framework | LangGraph | Explicit state graph, loops, conditional edges |
| Chunking | AST-aware (tree-sitter) | 30-40% better retrieval vs text chunking |
| Vector DB | ChromaDB → Qdrant (V3) | Zero-config for V1; abstract interface for migration |
| Database | PostgreSQL + asyncpg | Simpler than MSSQL, excellent async support |
| Memory | Session (Redis) + Long-term (PostgreSQL) | Fast access, automatic consolidation, persistent learning |
| Review | Adversarial agent (V1.2) | Separate agent catches bugs collaborative approach misses |

## Roadmap

**V1.2** (current): Tool-use loop, review agent, memory system, 8 languages, PostgreSQL

**V2**: Team support, Git webhooks, JetBrains plugin, LLM intent classification

**V3**: Qdrant migration, autonomous debugging agent, enterprise SSO, Kubernetes

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add features, agents, and language support.

See [docs/development/](docs/development/) for implementation details, completion reports, and technical deep-dives.

```bash
# Run tests
pytest

# Quality checks
ruff check app tests && black --check app tests && mypy app --ignore-missing-imports
```

## License

MIT
