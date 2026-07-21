"""DIP Phase 3 — Semantic Intelligence Layer (embeddings, vectors, semantic index)

Purely additive: 5 new tables, zero changes to any existing table. Every FK
points at existing frozen tables (knowledge_objects, document_chunks) —
nothing in Phase 1/2/2.5/2.6 is touched.

Revision ID: 0010_semantic_platform
Revises: 0009_knowledge_platform
Create Date: 2026-07-20 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0010_semantic_platform'
down_revision: Union[str, None] = '0009_knowledge_platform'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'embedding_jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('knowledge_id', sa.String(36), sa.ForeignKey('knowledge_objects.id'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='queued'),
        sa.Column('current_stage', sa.String(30), nullable=False, server_default=''),
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('dead_lettered', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('correlation_id', sa.String(36), nullable=False,
                   server_default=sa.text('gen_random_uuid()::text')),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_embedding_jobs_knowledge', 'embedding_jobs', ['knowledge_id'])

    op.create_table(
        'embedding_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('embedding_jobs.id'), nullable=False),
        sa.Column('knowledge_id', sa.String(36), nullable=False),
        sa.Column('embedding_id', sa.String(36), nullable=True),
        sa.Column('event_type', sa.String(40), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='completed'),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('detail_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_embedding_events_job', 'embedding_events', ['job_id', 'created_at'])

    op.create_table(
        'embedding_records',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('knowledge_id', sa.String(36), sa.ForeignKey('knowledge_objects.id'), nullable=False),
        sa.Column('chunk_id', sa.String(36), sa.ForeignKey('document_chunks.id'), nullable=False),
        sa.Column('embedding_version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('provider_name', sa.String(30), nullable=False),
        sa.Column('provider_version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('model_name', sa.String(100), nullable=False, server_default=''),
        sa.Column('model_version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('dimension', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('vector_checksum', sa.String(64), nullable=False, server_default=''),
        sa.Column('status', sa.String(20), nullable=False, server_default='queued'),
        sa.Column('quality_score', sa.Float(), nullable=True),
        sa.Column('migration_status', sa.String(20), nullable=False, server_default='not_started'),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('correlation_id', sa.String(36), nullable=False,
                   server_default=sa.text('gen_random_uuid()::text')),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_embedding_records_knowledge', 'embedding_records', ['knowledge_id'])
    op.create_index('ix_embedding_records_chunk', 'embedding_records', ['chunk_id'])
    op.create_unique_constraint(
        'uq_embedding_chunk_version', 'embedding_records', ['chunk_id', 'embedding_version']
    )

    op.create_table(
        'semantic_manifests',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('knowledge_id', sa.String(36), sa.ForeignKey('knowledge_objects.id'), nullable=False),
        sa.Column('vector_store_provider', sa.String(30), nullable=False, server_default=''),
        sa.Column('collection_name', sa.String(100), nullable=False, server_default=''),
        sa.Column('index_name', sa.String(100), nullable=False, server_default=''),
        sa.Column('embedding_version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('provider_name', sa.String(30), nullable=False, server_default=''),
        sa.Column('model_name', sa.String(100), nullable=False, server_default=''),
        sa.Column('dimension', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('embedding_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='queued'),
        sa.Column('current_index_version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('similarity_strategy', sa.String(30), nullable=False, server_default='cosine'),
        sa.Column('ranking_strategy', sa.String(30), nullable=True),
        sa.Column('retrieval_strategy', sa.String(30), nullable=True),
        sa.Column('correlation_id', sa.String(36), nullable=False,
                   server_default=sa.text('gen_random_uuid()::text')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_semantic_manifests_knowledge', 'semantic_manifests', ['knowledge_id'], unique=True)

    op.create_table(
        'semantic_indexes',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('index_name', sa.String(100), nullable=False),
        sa.Column('collection_name', sa.String(100), nullable=False),
        sa.Column('vector_store_provider', sa.String(30), nullable=False),
        sa.Column('embedding_version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('dimension', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('vector_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='creating'),
        sa.Column('health_status', sa.String(20), nullable=False, server_default='healthy'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        'uq_index_collection_version', 'semantic_indexes', ['collection_name', 'embedding_version']
    )


def downgrade() -> None:
    op.drop_constraint('uq_index_collection_version', 'semantic_indexes', type_='unique')
    op.drop_table('semantic_indexes')

    op.drop_index('ix_semantic_manifests_knowledge', table_name='semantic_manifests')
    op.drop_table('semantic_manifests')

    op.drop_constraint('uq_embedding_chunk_version', 'embedding_records', type_='unique')
    op.drop_index('ix_embedding_records_chunk', table_name='embedding_records')
    op.drop_index('ix_embedding_records_knowledge', table_name='embedding_records')
    op.drop_table('embedding_records')

    op.drop_index('ix_embedding_events_job', table_name='embedding_events')
    op.drop_table('embedding_events')

    op.drop_index('ix_embedding_jobs_knowledge', table_name='embedding_jobs')
    op.drop_table('embedding_jobs')
