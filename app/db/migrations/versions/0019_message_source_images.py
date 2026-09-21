"""Web search — which sources contributed a shown picture, and what was searched.

``show_image`` marks the one or two sources whose preview image was displayed
with the answer; without it a reload keeps the links and silently loses the
pictures. ``query`` repeats the search on each row so the header can still say
what was looked up after a refresh.

Both additive. Existing rows get show_image=false and query=NULL, which renders
exactly as those answers already do.

Revision ID: 0019_message_source_images
Revises: 0018_message_sources
Create Date: 2026-09-21 09:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0019_message_source_images'
down_revision: str | None = '0018_message_sources'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'message_sources',
        sa.Column('show_image', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column('message_sources', sa.Column('query', sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column('message_sources', 'query')
    op.drop_column('message_sources', 'show_image')
