"""
Repository Pattern for database access.

All database queries go through repository classes.
No raw SQL or ORM calls outside this module.
Repositories are injected into service classes via FastAPI dependency injection.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditLog,
    Conversation,
    IndexedFile,
    IndexJob,
    Message,
    MessageImage,
    Organization,
    Repository,
    RepositoryAccess,
    User,
    AgentExecution,
)


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: str) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, org_id: str, email: str) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(User.org_id == org_id, User.email == email)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> User:  # noqa: ANN003
        user = User(**kwargs)
        self.session.add(user)
        await self.session.flush()
        return user

    async def update_last_login(self, user_id: str) -> None:
        await self.session.execute(
            update(User)
            .where(User.id == user_id)
            .values(last_login_at=datetime.now(timezone.utc))
        )


class RepositoryRepo:
    """Repository for Repository entities (naming is awkward but accurate)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, repo_id: str) -> Optional[Repository]:
        result = await self.session.execute(
            select(Repository).where(Repository.id == repo_id)
        )
        return result.scalar_one_or_none()

    async def list_for_org(self, org_id: str) -> list[Repository]:
        result = await self.session.execute(
            select(Repository)
            .where(Repository.org_id == org_id)
            .order_by(Repository.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_for_user(self, user_id: str) -> list[Repository]:
        """Return only repos the user has explicit access to."""
        result = await self.session.execute(
            select(Repository)
            .join(RepositoryAccess, Repository.id == RepositoryAccess.repo_id)
            .where(RepositoryAccess.user_id == user_id)
            .order_by(Repository.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(self, **kwargs) -> Repository:  # noqa: ANN003
        repo = Repository(**kwargs)
        self.session.add(repo)
        await self.session.flush()
        return repo

    async def update_status(
        self,
        repo_id: str,
        status: str,
        last_indexed_at: Optional[datetime] = None,
        file_count: Optional[int] = None,
        chunk_count: Optional[int] = None,
    ) -> None:
        values: dict = {"index_status": status}
        if last_indexed_at is not None:
            values["last_indexed_at"] = last_indexed_at
        if file_count is not None:
            values["file_count"] = file_count
        if chunk_count is not None:
            values["chunk_count"] = chunk_count
        await self.session.execute(
            update(Repository).where(Repository.id == repo_id).values(**values)
        )

    async def has_access(self, user_id: str, repo_id: str, min_permission: str = "read") -> bool:
        """Check if a user has at least the specified permission on a repo."""
        permission_levels = {"read": 0, "write": 1, "admin": 2}
        min_level = permission_levels.get(min_permission, 0)

        result = await self.session.execute(
            select(RepositoryAccess).where(
                RepositoryAccess.repo_id == repo_id,
                RepositoryAccess.user_id == user_id,
            )
        )
        access = result.scalar_one_or_none()
        if access is None:
            return False
        return permission_levels.get(access.permission, 0) >= min_level

    async def grant_access(self, repo_id: str, user_id: str, permission: str = "read") -> None:
        access = RepositoryAccess(repo_id=repo_id, user_id=user_id, permission=permission)
        self.session.add(access)
        await self.session.flush()


class IndexJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, job_id: str) -> Optional[IndexJob]:
        result = await self.session.execute(
            select(IndexJob).where(IndexJob.id == job_id)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> IndexJob:  # noqa: ANN003
        job = IndexJob(**kwargs)
        self.session.add(job)
        await self.session.flush()
        return job

    async def update_progress(
        self,
        job_id: str,
        files_processed: int,
        chunks_created: int,
        status: Optional[str] = None,
        files_total: Optional[int] = None,
    ) -> None:
        values: dict = {
            "files_processed": files_processed,
            "chunks_created": chunks_created,
        }
        if files_total is not None:
            values["files_total"] = files_total
        if status:
            values["status"] = status
            if status == "running":
                values["started_at"] = datetime.now(timezone.utc)
            elif status in ("completed", "failed", "cancelled"):
                values["completed_at"] = datetime.now(timezone.utc)
        await self.session.execute(
            update(IndexJob).where(IndexJob.id == job_id).values(**values)
        )

    async def fail(self, job_id: str, error_message: str) -> None:
        await self.session.execute(
            update(IndexJob)
            .where(IndexJob.id == job_id)
            .values(
                status="failed",
                error_message=error_message,
                completed_at=datetime.now(timezone.utc),
            )
        )


class IndexedFileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_path(self, repo_id: str, file_path: str) -> Optional[IndexedFile]:
        result = await self.session.execute(
            select(IndexedFile).where(
                IndexedFile.repo_id == repo_id,
                IndexedFile.file_path == file_path,
            )
        )
        return result.scalar_one_or_none()

    async def get_hash(self, repo_id: str, file_path: str) -> Optional[str]:
        """Fast hash lookup — used by incremental indexing."""
        existing = await self.get_by_path(repo_id, file_path)
        return existing.file_hash if existing else None

    async def delete(self, repo_id: str, file_path: str) -> None:
        """Delete a file record — used when a file is removed from disk."""
        from sqlalchemy import delete
        await self.session.execute(
            delete(IndexedFile).where(
                IndexedFile.repo_id == repo_id,
                IndexedFile.file_path == file_path,
            )
        )

    async def delete_all_for_repo(self, repo_id: str) -> None:
        """Delete all file records for a repository — used on repo deletion."""
        from sqlalchemy import delete
        await self.session.execute(
            delete(IndexedFile).where(IndexedFile.repo_id == repo_id)
        )

    async def upsert(
        self,
        repo_id: str,
        file_path: str,
        language: Optional[str],
        file_hash: str,
        size_bytes: int,
        chunk_count: int,
    ) -> None:
        existing = await self.get_by_path(repo_id, file_path)
        if existing:
            existing.language = language
            existing.file_hash = file_hash
            existing.size_bytes = size_bytes
            existing.chunk_count = chunk_count
            existing.last_indexed_at = datetime.now(timezone.utc)
        else:
            self.session.add(
                IndexedFile(
                    repo_id=repo_id,
                    file_path=file_path,
                    language=language,
                    file_hash=file_hash,
                    size_bytes=size_bytes,
                    chunk_count=chunk_count,
                )
            )
        await self.session.flush()


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, conv_id: str) -> Optional[Conversation]:
        from sqlalchemy.orm import selectinload
        result = await self.session.execute(
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .where(Conversation.id == conv_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: str, limit: int = 20, offset: int = 0, include_archived: bool = False) -> tuple[list[Conversation], int]:
        """
        List conversations for a user with pagination.
        Returns (conversations, total_count)
        
        Pinned conversations are always shown first, then sorted by updated_at DESC.
        """
        from sqlalchemy import func, case
        
        # Build base query
        query = select(Conversation).where(Conversation.user_id == user_id)
        
        if not include_archived:
            query = query.where(Conversation.is_archived.is_(False))  # noqa: E712
        
        # Order: pinned first (by pin_order), then by updated_at DESC
        query = query.order_by(
            case(
                (Conversation.is_pinned.is_(True), Conversation.pin_order),
                else_=999999
            ),
            Conversation.updated_at.desc()
        )
        
        # Get total count
        count_query = select(func.count()).select_from(Conversation).where(Conversation.user_id == user_id)
        if not include_archived:
            count_query = count_query.where(Conversation.is_archived.is_(False))  # noqa: E712
        
        total = await self.session.execute(count_query)
        total_count = total.scalar() or 0
        
        # Apply pagination
        query = query.limit(limit).offset(offset)
        
        result = await self.session.execute(query)
        conversations = list(result.scalars().all())
        
        return conversations, total_count

    async def create(self, **kwargs) -> Conversation:  # noqa: ANN003
        conv = Conversation(**kwargs)
        self.session.add(conv)
        await self.session.flush()
        return conv

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        agent_used: Optional[str] = None,
        tokens_used: int = 0,
        latency_ms: Optional[int] = None,
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            agent_used=agent_used,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
        )
        self.session.add(msg)
        await self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(
                updated_at=datetime.now(timezone.utc),
                total_tokens=Conversation.total_tokens + tokens_used,
            )
        )
        await self.session.flush()
        return msg

    async def record_agent_execution(
        self,
        message_id: str,
        agent_name: str,
        status: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        tools_called_json: Optional[str] = None,
        duration_ms: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> AgentExecution:
        execution = AgentExecution(
            message_id=message_id,
            agent_name=agent_name,
            status=status,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            tools_called_json=tools_called_json,
            duration_ms=duration_ms,
            error_message=error_message,
        )
        self.session.add(execution)
        await self.session.flush()
        return execution

    async def update_title(self, conversation_id: str, title: str) -> None:
        """Update conversation title."""
        await self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(title=title, updated_at=datetime.now(timezone.utc))
        )

    async def delete_conversation(self, conversation_id: str) -> None:
        """Delete a conversation and all its messages, images, and documents."""
        from sqlalchemy import delete
        from app.db.models import MessageDocument
        # Delete images and documents first (FK to messages)
        await self.session.execute(
            delete(MessageImage).where(MessageImage.conversation_id == conversation_id)
        )
        await self.session.execute(
            delete(MessageDocument).where(MessageDocument.conversation_id == conversation_id)
        )
        # Delete messages (FK to conversation)
        await self.session.execute(
            delete(Message).where(Message.conversation_id == conversation_id)
        )
        # Delete conversation
        await self.session.execute(
            delete(Conversation).where(Conversation.id == conversation_id)
        )

    async def pin_conversation(self, conversation_id: str, user_id: str) -> None:
        """Pin a conversation to the top."""
        # Get current max pin_order for this user
        from sqlalchemy import func
        result = await self.session.execute(
            select(func.max(Conversation.pin_order))
            .where(Conversation.user_id == user_id, Conversation.is_pinned.is_(True))
        )
        max_order = result.scalar() or 0
        
        # Pin with next order
        await self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(is_pinned=True, pin_order=max_order + 1)
        )

    async def unpin_conversation(self, conversation_id: str) -> None:
        """Unpin a conversation."""
        await self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(is_pinned=False, pin_order=None)
        )

    async def archive_conversation(self, conversation_id: str) -> None:
        """Archive a conversation."""
        await self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(is_archived=True, updated_at=datetime.now(timezone.utc))
        )

    async def auto_generate_title(self, conversation_id: str, first_message: str) -> None:
        """Auto-generate title from first message."""
        # Take first 50 characters, clean up
        title = first_message.strip()[:50]
        if len(first_message) > 50:
            title += "..."
        
        await self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(title=title)
        )


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def log(
        self,
        org_id: str,
        action: str,
        user_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        metadata_json: Optional[str] = None,
        ip_address: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        entry = AuditLog(
            user_id=user_id,
            org_id=org_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_json=metadata_json,
            ip_address=ip_address,
            request_id=request_id,
        )
        self.session.add(entry)
        await self.session.flush()
