"""
DIP audit logging — writes to the platform's single immutable audit trail
(audit_logs table) under the `document.*` action namespace, rather than
inventing a parallel audit table.

Actions: document.upload, document.upload_failed, document.download,
document.delete, document.duplicate_rejected
"""
from __future__ import annotations

import json
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog


class DocumentAuditLogger:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def log(
        self,
        action: str,
        org_id: str,
        user_id: Optional[str],
        document_id: Optional[str],
        detail: Optional[dict[str, Any]] = None,
        request_id: Optional[str] = None,
    ) -> None:
        self._db.add(
            AuditLog(
                user_id=user_id,
                org_id=org_id,
                action=f"document.{action}",
                resource_type="document",
                resource_id=document_id,
                metadata_json=json.dumps(detail) if detail else None,
                request_id=request_id,
            )
        )
        await self._db.flush()
