"""
SQLAlchemy ORM models.

Every model maps to one MSSQL table.
All primary keys are UUID (generated in Python, not the DB).
All timestamps are UTC.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ─────────────────────────────────────────────────────────────────────────────
# IDENTITY & ACCESS
# ─────────────────────────────────────────────────────────────────────────────


class Organization(Base):
    """
    Root of the multi-tenancy model.
    Every user, repository, and conversation belongs to an org.
    """

    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    plan: Mapped[str] = mapped_column(String(20), nullable=False, default="free")
    max_repos: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    max_users: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    settings_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    users: Mapped[list[User]] = relationship("User", back_populates="organization")
    repositories: Mapped[list[Repository]] = relationship(
        "Repository", back_populates="organization"
    )


class User(Base):
    """
    A developer who uses the system.
    Role controls what they can do (admin/developer/viewer).
    
    Auth providers:
    - email: Traditional email/password (hashed_password set)
    - google: Google Sign-In via Firebase (firebase_uid set)
    - apple: Apple Sign-In via Firebase (firebase_uid set)
    - microsoft: Microsoft Sign-In via Firebase (firebase_uid set)
    - github: GitHub Sign-In via Firebase (firebase_uid set)
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_users_org_email"),
        Index("ix_users_firebase_uid", "firebase_uid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="developer"
    )  # admin|developer|viewer
    
    # Firebase OAuth fields (V1.2+)
    auth_provider: Mapped[str] = mapped_column(
        String(20), nullable=False, default="email"
    )  # email|google|apple|microsoft|github
    firebase_uid: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, unique=True
    )  # Firebase user ID for OAuth users
    profile_picture_url: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )  # Profile picture from OAuth provider
    
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    organization: Mapped[Organization] = relationship(
        "Organization", back_populates="users"
    )
    api_keys: Mapped[list[APIKey]] = relationship("APIKey", back_populates="user")
    conversations: Mapped[list[Conversation]] = relationship(
        "Conversation", back_populates="user"
    )


class APIKey(Base):
    """
    Static API key for CLI/IDE extension access.
    The raw key is shown once at creation; only the hash is stored.
    """

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    scopes_json: Mapped[str] = mapped_column(String(500), nullable=False, default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    user: Mapped[User] = relationship("User", back_populates="api_keys")


# ─────────────────────────────────────────────────────────────────────────────
# REPOSITORY MANAGEMENT
# ─────────────────────────────────────────────────────────────────────────────


class Repository(Base):
    """
    A connected codebase. Can be a local path or a remote Git repo.
    index_status tracks the lifecycle: pending → indexing → ready | error.
    """

    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint("org_id", "local_path", name="uq_repo_org_path"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(20), nullable=False, default="local"
    )  # github|gitlab|bitbucket|local
    remote_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    local_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    default_branch: Mapped[str] = mapped_column(
        String(100), nullable=False, default="main"
    )
    index_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending|indexing|ready|error|stale
    last_indexed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_commit_sha: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    organization: Mapped[Organization] = relationship(
        "Organization", back_populates="repositories"
    )
    access_entries: Mapped[list[RepositoryAccess]] = relationship(
        "RepositoryAccess", back_populates="repository"
    )
    index_jobs: Mapped[list[IndexJob]] = relationship(
        "IndexJob", back_populates="repository"
    )
    indexed_files: Mapped[list[IndexedFile]] = relationship(
        "IndexedFile", back_populates="repository"
    )


class RepositoryAccess(Base):
    """
    Per-user, per-repo access control.
    Checked before every vector search and file operation.
    """

    __tablename__ = "repository_access"
    __table_args__ = (
        UniqueConstraint("repo_id", "user_id", name="uq_repo_access"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    repo_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.id"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    permission: Mapped[str] = mapped_column(
        String(10), nullable=False, default="read"
    )  # read|write|admin
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    repository: Mapped[Repository] = relationship(
        "Repository", back_populates="access_entries"
    )
    user: Mapped[User] = relationship("User")


# ─────────────────────────────────────────────────────────────────────────────
# INDEXING
# ─────────────────────────────────────────────────────────────────────────────


class IndexJob(Base):
    """
    Tracks a repository indexing operation.
    Long-running jobs (10–60 min for large repos) need persistent tracking.
    """

    __tablename__ = "index_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    repo_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.id"), nullable=False
    )
    triggered_by: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    job_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="full"
    )  # full|incremental|file
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued"
    )  # queued|running|completed|failed|cancelled
    files_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    files_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunks_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    repository: Mapped[Repository] = relationship(
        "Repository", back_populates="index_jobs"
    )


class IndexedFile(Base):
    """
    Records each file that has been indexed, including its SHA256 hash.
    The hash enables incremental indexing: skip if hash unchanged.
    """

    __tablename__ = "indexed_files"
    __table_args__ = (
        UniqueConstraint("repo_id", "file_path", name="uq_indexed_file"),
        Index("ix_indexed_files_repo", "repo_id", "file_path"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    repo_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("repositories.id"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(2000), nullable=False)
    language: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA256
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_indexed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    repository: Mapped[Repository] = relationship(
        "Repository", back_populates="indexed_files"
    )


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSATION
# ─────────────────────────────────────────────────────────────────────────────


class Conversation(Base):
    """
    A conversation session between a user and the assistant.
    Messages are loaded separately to avoid fetching all content on list views.
    
    Features:
    - is_pinned: Pin important conversations to top
    - pin_order: Order of pinned conversations (lower = higher priority)
    - is_archived: Hide old conversations
    - title: Auto-generated from first message or manually edited
    """

    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_pinned", "user_id", "is_pinned", "pin_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    repo_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("repositories.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(
        String(255), nullable=False, default="New Conversation"
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pin_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    user: Mapped[User] = relationship("User", back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(
        "Message", back_populates="conversation", order_by="Message.created_at"
    )


class Message(Base):
    """
    A single message in a conversation.
    role: user | assistant | system | tool
    """

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conv", "conversation_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    agent_used: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    conversation: Mapped[Conversation] = relationship(
        "Conversation", back_populates="messages"
    )
    agent_executions: Mapped[list[AgentExecution]] = relationship(
        "AgentExecution", back_populates="message"
    )


class AgentExecution(Base):
    """
    Records every agent invocation for debugging and billing.
    Answers: why did this take 45 seconds? which tool was called?
    """

    __tablename__ = "agent_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("messages.id"), nullable=False
    )
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="running"
    )  # running|completed|failed
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tools_called_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    message: Mapped[Message] = relationship("Message", back_populates="agent_executions")


# ─────────────────────────────────────────────────────────────────────────────
# AUDIT
# ─────────────────────────────────────────────────────────────────────────────


class AuditLog(Base):
    """
    Immutable audit trail for all security-relevant operations.
    Required for enterprise compliance. Never updated, only inserted.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_user_created", "user_id", "created_at"),
        Index("ix_audit_org_created", "org_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # "file.write" "terminal.execute"
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


# ─────────────────────────────────────────────────────────────────────────────
# MODEL CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────


class ModelConfig(Base):
    """
    Per-org model configuration. Allows different teams to use different models.
    """

    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    model_name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # "qwen2.5-coder:7b"
    model_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # chat|embedding|code
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    context_window: Mapped[int] = mapped_column(
        Integer, nullable=False, default=32768
    )
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
