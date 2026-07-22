"""DIP Phase 5.6 — workspace_conversations.status for soft-delete.

Additive column; existing rows default to 'active'. Delete-conversation is a
soft delete (status='archived') so turns and citations are never orphaned.

Revision ID: 0016_workspace_conversation_status
Revises: 0015_workspace_platform
Create Date: 2026-07-22 03:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0016_ws_conv_status'
down_revision: Union[str, None] = '0015_workspace_platform'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'workspace_conversations',
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
    )


def downgrade() -> None:
    op.drop_column('workspace_conversations', 'status')
