# Changelog

## [1.1.0] — 2024 (Current)

### Added

**Git + Files API Routers (Priority #3 Complete)**
- Files API: REST endpoints for file operations
  - GET /files/{repo_id}/tree - List directory tree with max depth
  - GET /files/{repo_id}/content - Read file content (5MB max)
  - POST /files/{repo_id}/content - Write/create files with backups
  - DELETE /files/{repo_id}/content - Delete files
  - POST /files/{repo_id}/search - Search files by name pattern
- Git API: REST endpoints for Git operations (read-only)
  - GET /git/{repo_id}/status - Git status (staged, modified, untracked)
  - GET /git/{repo_id}/diff - Show uncommitted changes
  - GET /git/{repo_id}/log - Commit history with pagination
  - GET /git/{repo_id}/branches - List all branches
  - GET /git/{repo_id}/show - Show specific commit details
  - GET /git/{repo_id}/blame - Line-by-line authorship
- Security features:
  - Path traversal protection
  - Binary file detection and rejection
  - File size limits (5MB)
  - Access control (read/write permissions)
  - Automatic backup creation before overwrite
- Language detection from file extensions (20+ languages)
- Parent directory auto-creation for writes
- Comprehensive error handling

**Memory System (Priority #2 Complete)****
- Session memory: Last 20 messages stored in Redis with 24h TTL
- Long-term memory: Important facts stored in Redis (V1) with 90-day TTL
- Memory consolidator: LLM-based fact extraction from conversations
- Memory manager: Unified interface for all memory operations
- Automatic memory loading in orchestrator graph (load_memory node)
- Automatic memory saving and consolidation (finalize node)
- Support for memory types: preference, fact, pattern, issue
- Importance scoring (0-1) for memory prioritization
- Memory filtering by repository, type
- Access tracking for memories (count, last accessed)
- Formatted context generation for LLM consumption
- Fire-and-forget consolidation (non-blocking)

**Tool-Use Loop (Priority #1 Complete)**
- LangGraph orchestrator with autonomous tool calling
- ToolPlanner: LLM-based tool selection
- ToolExecutor: Async execution with 30s timeout
- ToolRegistry: Central tool management
- 5 tools: read_file, write_file, search_code, git_diff, run_command
- Max 5 iterations with intelligent loop control
- Tool result integration in agent context
- Sequential tool execution (parallel in V2)
- Path traversal protection and safety checks
- Comprehensive error handling and recovery

### Tests
- Session memory: 8 unit tests (100% pass)
- Long-term memory: 12 unit tests (100% pass) 
- Memory manager: 12 unit tests (100% pass)
- Tool loop: 6 integration tests (100% pass)
- Total: 112/112 tests passing

### Documentation
- MEMORY_MODULE.md: Complete memory system documentation
- TOOL_USE_LOOP.md: Tool-use loop reference
- Updated README with memory features

## [1.0.0] — 2024-06-17

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
