"""DIP Phase 5.5 — Knowledge Workspace tables (Product Experience Layer).

Eight tables, all links into the frozen platforms' tables, all CASCADE.
No data backfill here — the default workspace is bootstrapped lazily by
WorkspaceService on first touch, which also adopts pre-existing documents,
conversations, and artifacts.

Revision ID: 0015_workspace_platform
Revises: 0014_generation_platform
Create Date: 2026-07-21 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0015_workspace_platform'
down_revision: Union[str, None] = '0014_generation_platform'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'workspaces',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(36), nullable=False),
        sa.Column('user_id', sa.String(36),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('description', sa.String(500), nullable=False, server_default=''),
        sa.Column('icon', sa.String(30), nullable=False, server_default='folder'),
        sa.Column('is_default', sa.Boolean, nullable=False, server_default=sa.text('false')),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('correlation_id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_workspaces_user', 'workspaces', ['user_id', 'created_at'])

    op.create_table(
        'workspace_documents',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(36),
                  sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', sa.String(36),
                  sa.ForeignKey('documents.id', ondelete='CASCADE'),
                  nullable=False, unique=True),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_workspace_documents_ws', 'workspace_documents',
                    ['workspace_id', 'added_at'])

    op.create_table(
        'workspace_conversations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(36),
                  sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('conversation_id', sa.String(36),
                  sa.ForeignKey('dip_conversations.id', ondelete='CASCADE'),
                  nullable=False, unique=True),
        sa.Column('title', sa.String(300), nullable=False, server_default='New conversation'),
        sa.Column('title_generated', sa.Boolean, nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_workspace_conversations_ws', 'workspace_conversations',
                    ['workspace_id', 'updated_at'])

    op.create_table(
        'conversation_documents',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('conversation_id', sa.String(36),
                  sa.ForeignKey('dip_conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('document_id', sa.String(36),
                  sa.ForeignKey('documents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('conversation_id', 'document_id', name='uq_conversation_document'),
    )
    op.create_index('ix_conversation_documents_conv', 'conversation_documents',
                    ['conversation_id'])

    op.create_table(
        'workspace_artifacts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(36),
                  sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('artifact_id', sa.String(36),
                  sa.ForeignKey('generation_artifacts.id', ondelete='CASCADE'),
                  nullable=False, unique=True),
        sa.Column('conversation_id', sa.String(36), nullable=True),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_workspace_artifacts_ws', 'workspace_artifacts',
                    ['workspace_id', 'added_at'])

    op.create_table(
        'workspace_timeline',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(36),
                  sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.String(40), nullable=False),
        sa.Column('ref_type', sa.String(30), nullable=True),
        sa.Column('ref_id', sa.String(36), nullable=True),
        sa.Column('title', sa.String(300), nullable=False, server_default=''),
        sa.Column('detail_json', sa.Text, nullable=True),
        sa.Column('correlation_id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_workspace_timeline_ws', 'workspace_timeline',
                    ['workspace_id', 'created_at'])

    op.create_table(
        'workspace_bookmarks',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(36),
                  sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('target_type', sa.String(20), nullable=False),
        sa.Column('target_id', sa.String(36), nullable=False),
        sa.Column('note', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('workspace_id', 'target_type', 'target_id', name='uq_ws_bookmark'),
    )
    op.create_index('ix_workspace_bookmarks_ws', 'workspace_bookmarks',
                    ['workspace_id', 'created_at'])

    op.create_table(
        'workspace_summaries',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(36),
                  sa.ForeignKey('workspaces.id', ondelete='CASCADE'),
                  nullable=False, unique=True),
        sa.Column('summary', sa.Text, nullable=False, server_default=''),
        sa.Column('stats_json', sa.Text, nullable=True),
        sa.Column('suggestions_json', sa.Text, nullable=True),
        sa.Column('model', sa.String(100), nullable=False, server_default=''),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('workspace_summaries')
    op.drop_table('workspace_bookmarks')
    op.drop_table('workspace_timeline')
    op.drop_table('workspace_artifacts')
    op.drop_table('conversation_documents')
    op.drop_table('workspace_conversations')
    op.drop_table('workspace_documents')
    op.drop_table('workspaces')
