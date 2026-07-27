"""DIP Phase 5.8 — workspace_conversations.retrieval_mode (all|selected).

Explicit retrieval scope per conversation: 'all' uses every workspace
document; 'selected' uses only the conversation's attached documents.
Additive column; existing rows default to 'all' (matches prior implicit
behavior when no documents were attached).

Revision ID: 0017_conv_retrieval_mode
Revises: 0016_ws_conv_status
Create Date: 2026-07-23 04:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0017_conv_retrieval_mode'
down_revision: Union[str, None] = '0016_ws_conv_status'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'workspace_conversations',
        sa.Column('retrieval_mode', sa.String(20), nullable=False, server_default='all'),
    )


def downgrade() -> None:
    op.drop_column('workspace_conversations', 'retrieval_mode')
