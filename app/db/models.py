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
    images: Mapped[list["MessageImage"]] = relationship(
        "MessageImage", back_populates="message", lazy="selectin"
    )
    documents: Mapped[list["MessageDocument"]] = relationship(
        "MessageDocument", back_populates="message", lazy="selectin"
    )
    agent_executions: Mapped[list[AgentExecution]] = relationship(
        "AgentExecution", back_populates="message"
    )


class MessageImage(Base):
    """
    An image attached to a message.
    Stored on disk, metadata in DB for persistence across page refreshes.
    """

    __tablename__ = "message_images"
    __table_args__ = (
        Index("ix_message_images_msg", "message_id"),
        Index("ix_message_images_conv", "conversation_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("messages.id"), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    image_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    message: Mapped[Message] = relationship("Message", back_populates="images")


class MessageDocument(Base):
    """
    A document (PDF / Word / text) attached to a message.
    Original file + extracted text stored on disk, metadata in DB so
    attachments persist across page refreshes and follow-up Q&A can
    rebuild conversation document context after the Redis TTL expires.
    """

    __tablename__ = "message_documents"
    __table_args__ = (
        Index("ix_message_documents_msg", "message_id"),
        Index("ix_message_documents_conv", "conversation_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("messages.id"), nullable=False
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    text_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    doc_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )

    message: Mapped[Message] = relationship("Message", back_populates="documents")


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


# ─────────────────────────────────────────────────────────────────────────────
# DOCUMENT INTELLIGENCE PLATFORM (Phase 1 — storage foundation)
# ─────────────────────────────────────────────────────────────────────────────


class Document(Base):
    """
    A document in the Document Intelligence Platform.

    Phase 1: metadata for a binary stored in blob storage (S3). The binary
    NEVER lives in this table. Later phases (parsing, chunking, embeddings,
    RAG, generation) reference this row by id — this schema is the platform's
    root entity and must stay storage-provider-agnostic.

    Client-facing identifiers are the UUID `id` only; storage_bucket and
    storage_key are internal and never serialized to API responses.
    """

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_owner_created", "uploaded_by", "created_at"),
        Index("ix_documents_owner_checksum", "uploaded_by", "checksum_sha256"),
        Index("ix_documents_filename", "original_filename"),
        Index("ix_documents_status", "upload_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    uploaded_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str] = mapped_column(String(20), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    storage_provider: Mapped[str] = mapped_column(String(20), nullable=False)
    storage_bucket: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False)

    upload_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="uploading"
    )  # uploading|completed|failed
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tags_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Phase 2: knowledge-pipeline state, mirrored here for cheap listing.
    # none|queued|processing|parsed|normalized|knowledge_ready|failed
    processing_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="none"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class KnowledgeObject(Base):
    """
    Phase 2 head entity: the structured knowledge representation of one
    document. Structure is the serialized DocumentNode tree; chunks reference
    this row. Future phases consume KnowledgeObjects, never raw files.
    """

    __tablename__ = "knowledge_objects"
    __table_args__ = (
        Index("ix_knowledge_objects_doc", "document_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False)  # extension
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="unknown")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    table_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    section_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    structure_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Architecture Hardening — versioning (Objective 5)
    parser_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    chunk_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    processing_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")

    # Architecture Hardening — Knowledge Registry (Objective 10). Status
    # columns are placeholders future phases flip; nothing writes non-default
    # values to them yet.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    embedding_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_started")
    index_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_started")
    retrieval_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_started")
    generation_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_started")
    parent_knowledge_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("knowledge_objects.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class DocumentChunk(Base):
    """A retrieval-ready semantic chunk (structure-aware, not string-split)."""

    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_document_chunks_doc_seq", "document_id", "seq"),
        Index("ix_document_chunks_ko", "knowledge_object_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=False
    )
    knowledge_object_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_objects.id"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    node_type: Mapped[str] = mapped_column(String(20), nullable=False, default="paragraph")
    section_path: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class DocumentMetadataRow(Base):
    """Extracted + enriched metadata for one document (1:1)."""

    __tablename__ = "document_metadata"

    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), primary_key=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    author: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    source_created: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    source_modified: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="unknown")
    page_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sheet_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    slide_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    encoding: Mapped[str] = mapped_column(String(30), nullable=False, default="utf-8")
    custom_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class DocumentImage(Base):
    """An image extracted from a document — binary in blob storage."""

    __tablename__ = "document_images"
    __table_args__ = (Index("ix_document_images_doc", "document_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=False
    )
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    format: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class DocumentProcessingJob(Base):
    """One processing run for one document (retries create new attempts)."""

    __tablename__ = "document_processing_jobs"
    __table_args__ = (Index("ix_doc_processing_jobs_doc", "document_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    current_stage: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Architecture Hardening — profiles (Objective 6) + retry/DLQ (Objective 7)
    profile: Mapped[str] = mapped_column(String(30), nullable=False, default="standard")
    dead_lettered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Architecture Hardening 2.6 — platform-wide tracing (Objective 4). Root
    # correlation for this document: minted once at upload, carried forward
    # across every retry attempt so one ID traces the whole lifecycle.
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, default=_uuid)

    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class DocumentProcessingEvent(Base):
    """
    Append-only per-stage event log — serves as both parser log and
    processing history (an event stream subsumes both).
    """

    __tablename__ = "document_processing_events"
    __table_args__ = (Index("ix_doc_processing_events_job", "job_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document_processing_jobs.id"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # started|completed|failed|skipped
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    detail_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


# ─────────────────────────────────────────────────────────────────────────────
# KNOWLEDGE PLATFORM (Phase 2.6 — lifecycle, events, lineage)
# ─────────────────────────────────────────────────────────────────────────────


class KnowledgeManifest(Base):
    """
    The operational dashboard model for one Knowledge Object (Objective 3).
    KnowledgeObject (Phase 2) stays the stable content/registry row; this is
    its lifecycle/health/versioning sidecar — kept separate so nothing about
    Phase 2's tested `KnowledgeObject.status` semantics changes.

    parser_version/chunk_version/processing_version/schema_version are
    intentionally denormalized copies of KnowledgeObject's — both are
    written from the same local variables in one transaction (the
    orchestrator), never computed twice, so there is no drift risk despite
    the duplication.
    """

    __tablename__ = "knowledge_manifests"
    __table_args__ = (
        Index("ix_knowledge_manifests_ko", "knowledge_object_id", unique=True),
        Index("ix_knowledge_manifests_doc", "document_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    knowledge_object_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_objects.id"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=False
    )

    lifecycle_state: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    parser_name: Mapped[str] = mapped_column(String(50), nullable=False, default="")

    parser_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    chunk_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    embedding_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    knowledge_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    relationship_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    processing_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")

    validation_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    current_stage: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    capabilities_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    warnings_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    failures_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    content_identity_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, default=_uuid)
    workspace_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="org")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class KnowledgeEventRecord(Base):
    """Append-only Knowledge domain event log (Objective 2) — content
    lifecycle events, distinct from DocumentProcessingEvent's pipeline-stage
    log."""

    __tablename__ = "knowledge_events"
    __table_args__ = (
        Index("ix_knowledge_events_ko", "knowledge_id", "created_at"),
        Index("ix_knowledge_events_correlation", "correlation_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    knowledge_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    previous_state: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    current_state: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="system")
    metadata_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    warnings_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    errors_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class KnowledgeLineageEdge(Base):
    """
    Generic provenance graph (Objective 8). node_id/parent_id are NOT
    foreign keys — node_type varies (document/chunk/knowledge_object today;
    embedding/retrieval_result/generated_answer in future phases), so a
    single FK target is impossible by design. This is what makes future
    node types attach without a migration.
    """

    __tablename__ = "knowledge_lineage_edges"
    __table_args__ = (
        Index("ix_lineage_node", "node_type", "node_id"),
        Index("ix_lineage_parent", "parent_type", "parent_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    node_type: Mapped[str] = mapped_column(String(30), nullable=False)
    node_id: Mapped[str] = mapped_column(String(36), nullable=False)
    parent_type: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    parent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


# ─────────────────────────────────────────────────────────────────────────────
# SEMANTIC INTELLIGENCE LAYER (Phase 3 — embeddings, vectors, semantic index)
# ─────────────────────────────────────────────────────────────────────────────


class EmbeddingJob(Base):
    """One embedding run for one Knowledge Object (retries create new attempts).
    Mirrors DocumentProcessingJob exactly — same job-tracking pattern."""

    __tablename__ = "embedding_jobs"
    __table_args__ = (Index("ix_embedding_jobs_knowledge", "knowledge_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    knowledge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_objects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    current_stage: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dead_lettered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, default=_uuid)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class EmbeddingEventRecord(Base):
    """Append-only Semantic event log (Objective 11) — distinct from both
    DocumentProcessingEvent (pipeline stages) and KnowledgeEventRecord
    (content lifecycle)."""

    __tablename__ = "embedding_events"
    __table_args__ = (Index("ix_embedding_events_job", "job_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("embedding_jobs.id", ondelete="CASCADE"), nullable=False
    )
    knowledge_id: Mapped[str] = mapped_column(String(36), nullable=False)
    embedding_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    detail_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


class EmbeddingRecord(Base):
    """
    Embedding Registry (Objective 6) — ONE ROW PER CHUNK EMBEDDING. The
    vector floats themselves live in the vector store, never in Postgres;
    this row is metadata only (matches how Document tracks S3 keys, not
    file bytes). Multiple versions can coexist for the same chunk
    (Objective 13) — reprocessing creates new rows, never overwrites.
    """

    __tablename__ = "embedding_records"
    __table_args__ = (
        Index("ix_embedding_records_knowledge", "knowledge_id"),
        Index("ix_embedding_records_chunk", "chunk_id"),
        UniqueConstraint("chunk_id", "embedding_version", name="uq_embedding_chunk_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    knowledge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_objects.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False
    )

    embedding_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    provider_name: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    model_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    model_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    dimension: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    vector_checksum: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    migration_status: Mapped[str] = mapped_column(String(20), nullable=False, default="not_started")

    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, default=_uuid)

    generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class SemanticManifest(Base):
    """
    Semantic Registry (Objective 8) — one row per Knowledge Object,
    aggregating its embedding_records and pointing at the vector store/index
    that hold them. Knowledge Registry owns content; this owns semantic
    representation. Knowledge never references vectors directly.
    """

    __tablename__ = "semantic_manifests"
    __table_args__ = (Index("ix_semantic_manifests_knowledge", "knowledge_id", unique=True),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    knowledge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_objects.id", ondelete="CASCADE"), nullable=False
    )

    vector_store_provider: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    collection_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    index_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")

    embedding_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    provider_name: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    model_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    dimension: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    current_index_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    similarity_strategy: Mapped[str] = mapped_column(String(30), nullable=False, default="cosine")
    ranking_strategy: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)     # future
    retrieval_strategy: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)   # future

    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class SemanticIndex(Base):
    """
    Semantic Index management (Objective 9) — the index itself as a
    first-class entity, separate from any single Knowledge Object's
    manifest. One row per (collection, embedding_version) combination.
    Indexing only — no retrieval/query logic here.
    """

    __tablename__ = "semantic_indexes"
    __table_args__ = (
        UniqueConstraint("collection_name", "embedding_version", name="uq_index_collection_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    index_name: Mapped[str] = mapped_column(String(100), nullable=False)
    collection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    vector_store_provider: Mapped[str] = mapped_column(String(30), nullable=False)
    embedding_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    dimension: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vector_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="creating")
    health_status: Mapped[str] = mapped_column(String(20), nullable=False, default="healthy")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSATIONAL KNOWLEDGE INTELLIGENCE (Phase 4 — grounded Q&A over knowledge)
# ─────────────────────────────────────────────────────────────────────────────


class DipConversation(Base):
    """A knowledge-grounded conversation (Objective 1/13). Deliberately
    separate from the legacy chat `conversations` table — that system is
    frozen and serves a different product surface."""

    __tablename__ = "dip_conversations"
    __table_args__ = (Index("ix_dip_conversations_user", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )


class DipConversationTurn(Base):
    """One question → grounded answer exchange, with its citations and the
    full metric set (Objective 15) persisted on the row. CASCADE FKs from
    day one — the Phase 3 cross-process race taught that referential
    cleanup belongs to the database, not application statement ordering."""

    __tablename__ = "dip_conversation_turns"
    __table_args__ = (Index("ix_dip_turns_conversation", "conversation_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dip_conversations.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    intent: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="processing")
    grounded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    grounding_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    refusal_reason: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    citations_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    document_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)  # scope, if any

    # Objective 15 — per-turn metrics
    retrieval_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ranking_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    llm_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    streaming_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    llm_provider: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ConversationEventRecord(Base):
    """Append-only Conversation event log (Objective 14) — the analytics/
    monitoring stream, distinct from processing/knowledge/embedding events."""

    __tablename__ = "conversation_events"
    __table_args__ = (Index("ix_conversation_events_turn", "turn_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("dip_conversations.id", ondelete="CASCADE"), nullable=False
    )
    turn_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    detail_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )


# ─────────────────────────────────────────────────────────────────────────────
# INTELLIGENT CONTENT GENERATION (Phase 5 — planned artifacts, built files)
# ─────────────────────────────────────────────────────────────────────────────


class GenerationArtifact(Base):
    """
    Generation Registry + Manifest in one row (Objectives 14/15): what was
    requested, how it was planned/built (versions, builder, checksum), where
    the bytes live, and the full metric set. The file bytes live in blob
    storage, never in Postgres — same rule as documents and vectors.
    """

    __tablename__ = "generation_artifacts"
    __table_args__ = (Index("ix_generation_artifacts_user", "user_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    org_id: Mapped[str] = mapped_column(String(36), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")

    title: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    storage_key: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    content_type: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    checksum: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    spec_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    builder_name: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    builder_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")

    grounded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_document_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    source_knowledge_ids_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    planning_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    transform_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    build_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    store_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    llm_provider: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    llm_model: Mapped[str] = mapped_column(String(100), nullable=False, default="")

    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, default=_uuid)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class GenerationEventRecord(Base):
    """Append-only Generation event log (Objective 16)."""

    __tablename__ = "generation_events"
    __table_args__ = (Index("ix_generation_events_artifact", "artifact_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    artifact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("generation_artifacts.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    detail_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_now
    )
