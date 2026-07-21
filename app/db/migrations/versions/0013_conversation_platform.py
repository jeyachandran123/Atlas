"""DIP Phase 4 — Conversational Knowledge Intelligence tables.

dip_conversations / dip_conversation_turns / conversation_events. All
foreign keys carry ON DELETE CASCADE from day one — the Phase 3
cross-process race (fixed in 0011/0012) established that referential
cleanup belongs to the database, not application statement ordering.

Revision ID: 0013_conversation_platform
Revises: 0012_semantic_fk_cascade
Create Date: 2026-07-21 06:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0013_conversation_platform'
down_revision: Union[str, None] = '0012_semantic_fk_cascade'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'dip_conversations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('org_id', sa.String(36), nullable=False),
        sa.Column('title', sa.String(300), nullable=False, server_default=''),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('correlation_id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_dip_conversations_user', 'dip_conversations', ['user_id', 'created_at'])

    op.create_table(
        'dip_conversation_turns',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('conversation_id', sa.String(36),
                  sa.ForeignKey('dip_conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('seq', sa.Integer, nullable=False, server_default='0'),
        sa.Column('question', sa.Text, nullable=False),
        sa.Column('answer', sa.Text, nullable=True),
        sa.Column('intent', sa.String(30), nullable=False, server_default=''),
        sa.Column('status', sa.String(20), nullable=False, server_default='processing'),
        sa.Column('grounded', sa.Boolean, nullable=False, server_default=sa.text('false')),
        sa.Column('grounding_score', sa.Float, nullable=True),
        sa.Column('refusal_reason', sa.String(100), nullable=True),
        sa.Column('citations_json', sa.Text, nullable=True),
        sa.Column('document_id', sa.String(36), nullable=True),
        sa.Column('retrieval_ms', sa.Integer, nullable=True),
        sa.Column('ranking_ms', sa.Integer, nullable=True),
        sa.Column('llm_ms', sa.Integer, nullable=True),
        sa.Column('streaming_ms', sa.Integer, nullable=True),
        sa.Column('total_ms', sa.Integer, nullable=True),
        sa.Column('prompt_tokens', sa.Integer, nullable=True),
        sa.Column('completion_tokens', sa.Integer, nullable=True),
        sa.Column('total_tokens', sa.Integer, nullable=True),
        sa.Column('cost_estimate', sa.Float, nullable=False, server_default='0'),
        sa.Column('citation_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('llm_provider', sa.String(30), nullable=False, server_default=''),
        sa.Column('llm_model', sa.String(100), nullable=False, server_default=''),
        sa.Column('error', sa.Text, nullable=True),
        sa.Column('correlation_id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_dip_turns_conversation', 'dip_conversation_turns',
                    ['conversation_id', 'created_at'])

    op.create_table(
        'conversation_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('conversation_id', sa.String(36),
                  sa.ForeignKey('dip_conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('turn_id', sa.String(36), nullable=True),
        sa.Column('event_type', sa.String(40), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='completed'),
        sa.Column('duration_ms', sa.Integer, nullable=True),
        sa.Column('detail_json', sa.Text, nullable=True),
        sa.Column('correlation_id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_conversation_events_turn', 'conversation_events',
                    ['turn_id', 'created_at'])


def downgrade() -> None:
    op.drop_table('conversation_events')
    op.drop_table('dip_conversation_turns')
    op.drop_table('dip_conversations')
