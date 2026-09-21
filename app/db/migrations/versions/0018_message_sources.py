"""Web search — message_sources.

The pages an answer was built from, so the source cards survive a page refresh.
Streamed once while the reply is written; without these rows a reload shows the
answer with nothing behind it.

Additive and empty on creation: every existing message simply has no sources.

Revision ID: 0018_message_sources
Revises: 0017_conv_retrieval_mode
Create Date: 2026-09-21 08:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0018_message_sources'
down_revision: str | None = '0017_conv_retrieval_mode'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        'message_sources',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('message_id', sa.String(36), sa.ForeignKey('messages.id'), nullable=False),
        # The order the cards were shown in, which is what a "[2]" in the
        # answer refers to.
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('url', sa.String(2048), nullable=False),
        sa.Column('title', sa.String(512), nullable=False, server_default=''),
        sa.Column('domain', sa.String(255), nullable=False, server_default=''),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('thumbnail_url', sa.String(2048), nullable=True),
        sa.Column('favicon_url', sa.String(2048), nullable=True),
        sa.Column('published', sa.String(64), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index('ix_message_sources_msg', 'message_sources', ['message_id'])


def downgrade() -> None:
    op.drop_index('ix_message_sources_msg', table_name='message_sources')
    op.drop_table('message_sources')
