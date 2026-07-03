"""
Shared Pydantic schemas used across the application.

These are the data transfer objects (DTOs) that flow between
API layer, service layer, and agent layer.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────────
# ENUMERATIONS
# ─────────────────────────────────────────────────────────────────────────────


class ChunkType(str, Enum):
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    MODULE = "module"
    IMPORT = "import"
    DOCSTRING = "docstring"
    CONSTANT = "constant"


class IndexStatus(str, Enum):
    PENDING = "pending"
    INDEXING = "indexing"
    READY = "ready"
    ERROR = "error"
    STALE = "stale"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


# ─────────────────────────────────────────────────────────────────────────────
# CODE CHUNK — the core data structure of the system
# ─────────────────────────────────────────────────────────────────────────────


class CodeChunk(BaseModel):
    """
    A semantic unit of code extracted during indexing.
    One function = one chunk. One class = one chunk + N method chunks.
    """

    content: str
    file_path: str
    language: str
    chunk_type: ChunkType
    start_line: int
    end_line: int
    function_name: Optional[str] = None
    class_name: Optional[str] = None
    repo_id: str
    file_hash: str
    embedding: Optional[list[float]] = None  # V1.2+: for MMR similarity

    @property
    def display_location(self) -> str:
        return f"{self.file_path}:{self.start_line}-{self.end_line}"

    @property
    def token_estimate(self) -> int:
        """Rough token estimate: ~4 chars per token."""
        return len(self.content) // 4


class SearchResult(BaseModel):
    """A retrieved code chunk with its relevance score."""

    chunk: CodeChunk
    score: float
    rank: int


class ContextWindow(BaseModel):
    """
    The assembled context ready to be injected into a prompt.
    Respects token budget; lower-priority chunks are compressed or omitted.
    """

    chunks: list[SearchResult]
    total_tokens: int
    budget_used: float  # 0.0 - 1.0
    compressed_count: int = 0  # chunks that were summarised
    omitted_count: int = 0  # chunks that didn't fit

    def format_for_prompt(self) -> str:
        """Format all chunks as a readable context block for the LLM."""
        parts = []
        for result in self.chunks:
            chunk = result.chunk
            header = f"# {chunk.file_path} (lines {chunk.start_line}-{chunk.end_line})"
            if chunk.function_name:
                header += f" — {chunk.chunk_type.value}: {chunk.function_name}"
            elif chunk.class_name:
                header += f" — {chunk.chunk_type.value}: {chunk.class_name}"
            parts.append(f"{header}\n```{chunk.language}\n{chunk.content}\n```")
        return "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# TOOL SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────


class ToolResult(BaseModel):
    """Standardised output from any tool execution."""

    tool_name: str
    success: bool
    output: Any = None
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    """Represents a planned tool invocation from the LLM."""

    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)
    rationale: Optional[str] = None  # Why this tool is being called


# ─────────────────────────────────────────────────────────────────────────────
# AGENT STATE — the shared object flowing through the LangGraph graph
# ─────────────────────────────────────────────────────────────────────────────


class AgentState(BaseModel):
    """
    State shared across all nodes in the LangGraph StateGraph.
    Agents read from it and write to it — they never call each other directly.
    """

    # Input
    user_message: str
    conversation_id: str
    repo_id: Optional[str] = None
    user_id: str
    org_id: str

    # Context
    code_context: list[SearchResult] = Field(default_factory=list)
    session_messages: list[dict[str, str]] = Field(default_factory=list)
    long_term_memories: list[str] = Field(default_factory=list)

    # Execution
    intent: str = "code"  # code|review|explain|search
    tool_results: list[ToolResult] = Field(default_factory=list)
    draft_output: str = ""
    review_feedback: str = ""
    revision_count: int = 0
    max_revisions: int = 2

    # Output
    final_response: str = ""
    files_modified: list[str] = Field(default_factory=list)
    error: Optional[str] = None

    # Telemetry
    request_id: str = ""
    start_time: Optional[datetime] = None


# ─────────────────────────────────────────────────────────────────────────────
# API RESPONSE WRAPPERS
# ─────────────────────────────────────────────────────────────────────────────


class APIResponse(BaseModel):
    """Standard API response wrapper."""

    status: str = "success"
    message: str = "OK"
    data: Any = None


class ErrorResponse(BaseModel):
    """Standard error response."""

    status: str = "error"
    message: str
    detail: Optional[str] = None
    request_id: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# DOMAIN SCHEMAS (used by API routers)
# ─────────────────────────────────────────────────────────────────────────────


class UserOut(BaseModel):
    id: str
    email: str
    full_name: Optional[str]
    role: str
    created_at: datetime


class RepoOut(BaseModel):
    id: str
    name: str
    local_path: str
    provider: str
    index_status: str
    file_count: int
    chunk_count: int
    last_indexed_at: Optional[datetime]
    created_at: datetime


class IndexJobOut(BaseModel):
    id: str
    repo_id: str
    job_type: str
    status: str
    files_total: int
    files_processed: int
    chunks_created: int
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime


class ConversationOut(BaseModel):
    id: str
    title: str
    repo_id: Optional[str]
    total_tokens: int
    is_pinned: bool = False
    pin_order: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    agent_used: Optional[str]
    tokens_used: int
    created_at: datetime


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    conversation_id: Optional[str] = None
    repo_id: Optional[str] = None
    agent_mode: str = Field(default="auto")  # auto | code | business


class ChatResponse(BaseModel):
    conversation_id: str
    message_id: str
    content: str
    agent_used: str
    tokens_used: int
    latency_ms: int
    context_chunks_used: int


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    repo_id: str
    top_k: int = Field(default=8, ge=1, le=20)
    language: Optional[str] = None
    chunk_type: Optional[ChunkType] = None
    file_path_filter: Optional[str] = None


class SearchResponse(BaseModel):
    results: list[SearchResult]
    total_found: int
    query: str
