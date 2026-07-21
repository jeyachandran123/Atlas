"""DIP Phase 5 — Intelligent Content Generation tables.

generation_artifacts (registry + manifest) and generation_events. CASCADE
FKs from day one, per the platform's established rule.

Revision ID: 0014_generation_platform
Revises: 0013_conversation_platform
Create Date: 2026-07-21 09:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0014_generation_platform'
down_revision: Union[str, None] = '0013_conversation_platform'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'generation_artifacts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('org_id', sa.String(36), nullable=False),
        sa.Column('prompt', sa.Text, nullable=False),
        sa.Column('format', sa.String(20), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='requested'),
        sa.Column('title', sa.String(300), nullable=False, server_default=''),
        sa.Column('filename', sa.String(255), nullable=False, server_default=''),
        sa.Column('storage_key', sa.String(1000), nullable=False, server_default=''),
        sa.Column('content_type', sa.String(100), nullable=False, server_default=''),
        sa.Column('checksum', sa.String(64), nullable=False, server_default=''),
        sa.Column('size_bytes', sa.Integer, nullable=False, server_default='0'),
        sa.Column('spec_version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('builder_name', sa.String(30), nullable=False, server_default=''),
        sa.Column('builder_version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('schema_version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('grounded', sa.Boolean, nullable=False, server_default=sa.text('false')),
        sa.Column('source_document_id', sa.String(36), nullable=True),
        sa.Column('source_knowledge_ids_json', sa.Text, nullable=True),
        sa.Column('planning_ms', sa.Integer, nullable=True),
        sa.Column('transform_ms', sa.Integer, nullable=True),
        sa.Column('build_ms', sa.Integer, nullable=True),
        sa.Column('store_ms', sa.Integer, nullable=True),
        sa.Column('total_ms', sa.Integer, nullable=True),
        sa.Column('prompt_tokens', sa.Integer, nullable=True),
        sa.Column('completion_tokens', sa.Integer, nullable=True),
        sa.Column('llm_provider', sa.String(30), nullable=False, server_default=''),
        sa.Column('llm_model', sa.String(100), nullable=False, server_default=''),
        sa.Column('error', sa.Text, nullable=True),
        sa.Column('correlation_id', sa.String(36), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_generation_artifacts_user', 'generation_artifacts',
                    ['user_id', 'created_at'])

    op.create_table(
        'generation_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('artifact_id', sa.String(36),
                  sa.ForeignKey('generation_artifacts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.String(40), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='completed'),
        sa.Column('duration_ms', sa.Integer, nullable=True),
        sa.Column('detail_json', sa.Text, nullable=True),
        sa.Column('correlation_id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_generation_events_artifact', 'generation_events',
                    ['artifact_id', 'created_at'])


def downgrade() -> None:
    op.drop_table('generation_events')
    op.drop_table('generation_artifacts')
