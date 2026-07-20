"""DIP Architecture Foundation Hardening — versioning, registry status, profiles, DLQ

Purely additive: every new column is nullable-free-with-server-default, so
existing rows need no backfill and no existing query behaviour changes.

Revision ID: 0008_dip_hardening
Revises: 0007_dip_knowledge
Create Date: 2026-07-20 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008_dip_hardening'
down_revision: Union[str, None] = '0007_dip_knowledge'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── knowledge_objects: versioning (Obj. 5) + registry status (Obj. 10) ──
    op.add_column('knowledge_objects', sa.Column('parser_version', sa.String(20), nullable=False, server_default='1.0.0'))
    op.add_column('knowledge_objects', sa.Column('chunk_version', sa.String(20), nullable=False, server_default='1.0.0'))
    op.add_column('knowledge_objects', sa.Column('processing_version', sa.String(20), nullable=False, server_default='1.0.0'))
    op.add_column('knowledge_objects', sa.Column('schema_version', sa.String(20), nullable=False, server_default='1.0.0'))
    op.add_column('knowledge_objects', sa.Column('status', sa.String(20), nullable=False, server_default='ready'))
    op.add_column('knowledge_objects', sa.Column('embedding_status', sa.String(20), nullable=False, server_default='not_started'))
    op.add_column('knowledge_objects', sa.Column('index_status', sa.String(20), nullable=False, server_default='not_started'))
    op.add_column('knowledge_objects', sa.Column('retrieval_status', sa.String(20), nullable=False, server_default='not_started'))
    op.add_column('knowledge_objects', sa.Column('generation_status', sa.String(20), nullable=False, server_default='not_started'))
    op.add_column('knowledge_objects', sa.Column('parent_knowledge_id', sa.String(36), sa.ForeignKey('knowledge_objects.id'), nullable=True))
    op.add_column('knowledge_objects', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))

    # ── document_processing_jobs: profiles (Obj. 6) + retry/DLQ (Obj. 7) ────
    op.add_column('document_processing_jobs', sa.Column('profile', sa.String(30), nullable=False, server_default='standard'))
    op.add_column('document_processing_jobs', sa.Column('dead_lettered', sa.Boolean(), nullable=False, server_default=sa.text('false')))


def downgrade() -> None:
    op.drop_column('document_processing_jobs', 'dead_lettered')
    op.drop_column('document_processing_jobs', 'profile')

    op.drop_column('knowledge_objects', 'updated_at')
    op.drop_column('knowledge_objects', 'parent_knowledge_id')
    op.drop_column('knowledge_objects', 'generation_status')
    op.drop_column('knowledge_objects', 'retrieval_status')
    op.drop_column('knowledge_objects', 'index_status')
    op.drop_column('knowledge_objects', 'embedding_status')
    op.drop_column('knowledge_objects', 'status')
    op.drop_column('knowledge_objects', 'schema_version')
    op.drop_column('knowledge_objects', 'processing_version')
    op.drop_column('knowledge_objects', 'chunk_version')
    op.drop_column('knowledge_objects', 'parser_version')
