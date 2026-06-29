# Changelog

## [1.0.0] — 2026-06-17

### Added

**Core Platform**
- FastAPI application with full async stack (SQLAlchemy 2.x, aioodbc, aioredis)
- JWT + API key authentication with RBAC (admin/developer/viewer)
- Rate limiting via slowapi per endpoint
- Prometheus metrics + OpenTelemetry tracing
- Structured JSON logging via loguru
- X-Request-ID propagation across all services

**Repository Indexing**
- Recursive file tree scanner with .gitignore support
- SHA256 content hashing for incremental indexing (skip unchanged files)
- AST-aware chunker using tree-sitter (Python fully implemented; JS/TS/Java/C#/Go via regex fallback)
- Chunker produces: functions, classes, methods, imports, module docstrings
- Batched async embedding via Ollama (nomic-embed-text)
- ChromaDB vector storage with one collection per repository
- Background worker via Redis BRPOP queue
- Distributed lock prevents duplicate index jobs
- Real-time progress streaming via Redis HSET

**Retrieval & Context**
- Semantic search via ChromaDB + cosine similarity
- MMR (Maximal Marginal Relevance) re-ranking for diversity
- Metadata filters: language, chunk_type, file_path
- Token-budget-aware context builder
- Context compression for lower-priority chunks
- Prompt assembly with structured context injection

**Agent System**
- LangGraph StateGraph orchestrator
- CodingAgent: code generation, bug fixing, explanation, test generation
- Intent detection: code / review / explain / search / chat
- Streaming SSE responses via FastAPI StreamingResponse

**Tools**
- FileTool: read/write/patch files with path traversal protection
- GitTool: read-only git log/diff/blame/status/branches
- SearchTool: semantic and symbol search
- TerminalTool: Docker-sandboxed command execution (with subprocess fallback for dev)

**Infrastructure**
- Multi-stage Dockerfile: runtime / worker / sandbox images
- Docker Compose with: API, worker, MSSQL, Redis, ChromaDB, Ollama, Prometheus, Grafana, Jaeger
- Alembic migrations with full initial schema
- GitHub Actions CI: lint, format, type-check, security scan, tests, Docker build

**Database**
- MSSQL schema: Organizations, Users, APIKeys, Repositories, RepositoryAccess, IndexJobs, IndexedFiles, Conversations, Messages, AgentExecutions, AuditLogs, ModelConfigs
- Repository Pattern for all DB access
- Redis: session memory (20-message sliding window), job queue, distributed locks, progress tracking, model health cache

## [Unreleased]

_Changes for V2 planned here._
