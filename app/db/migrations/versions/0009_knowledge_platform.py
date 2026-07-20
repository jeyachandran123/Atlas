"""DIP Phase 2.6 — Knowledge Platform Foundation Hardening

Purely additive: 3 new tables + 1 new column, every new field nullable-free
with a server default. Existing rows need no backfill for correctness; a
best-effort backfill of manifests for pre-2.6 knowledge_objects runs at the
end of upgrade() so nothing is orphaned.

Revision ID: 0009_knowledge_platform
Revises: 0008_dip_hardening
Create Date: 2026-07-20 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0009_knowledge_platform'
down_revision: Union[str, None] = '0008_dip_hardening'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'document_processing_jobs',
        sa.Column('correlation_id', sa.String(36), nullable=False,
                   server_default=sa.text('gen_random_uuid()::text')),
    )

    op.create_table(
        'knowledge_manifests',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('knowledge_object_id', sa.String(36), sa.ForeignKey('knowledge_objects.id'), nullable=False),
        sa.Column('document_id', sa.String(36), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('lifecycle_state', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('parser_name', sa.String(50), nullable=False, server_default=''),
        sa.Column('parser_version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('chunk_version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('embedding_version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('knowledge_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('relationship_version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('schema_version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('processing_version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('validation_status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('current_stage', sa.String(30), nullable=False, server_default=''),
        sa.Column('capabilities_json', sa.Text(), nullable=True),
        sa.Column('warnings_json', sa.Text(), nullable=True),
        sa.Column('failures_json', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('content_identity_json', sa.Text(), nullable=True),
        sa.Column('correlation_id', sa.String(36), nullable=False,
                   server_default=sa.text('gen_random_uuid()::text')),
        sa.Column('workspace_id', sa.String(36), nullable=True),
        sa.Column('visibility', sa.String(20), nullable=False, server_default='org'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_knowledge_manifests_ko', 'knowledge_manifests', ['knowledge_object_id'], unique=True)
    op.create_index('ix_knowledge_manifests_doc', 'knowledge_manifests', ['document_id'])

    op.create_table(
        'knowledge_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('event_type', sa.String(40), nullable=False),
        sa.Column('knowledge_id', sa.String(36), nullable=False),
        sa.Column('document_id', sa.String(36), nullable=False),
        sa.Column('correlation_id', sa.String(36), nullable=False),
        sa.Column('previous_state', sa.String(20), nullable=True),
        sa.Column('current_state', sa.String(20), nullable=True),
        sa.Column('version', sa.String(20), nullable=False, server_default='1.0.0'),
        sa.Column('source', sa.String(30), nullable=False, server_default='system'),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('warnings_json', sa.Text(), nullable=True),
        sa.Column('errors_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_knowledge_events_ko', 'knowledge_events', ['knowledge_id', 'created_at'])
    op.create_index('ix_knowledge_events_correlation', 'knowledge_events', ['correlation_id'])

    op.create_table(
        'knowledge_lineage_edges',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('node_type', sa.String(30), nullable=False),
        sa.Column('node_id', sa.String(36), nullable=False),
        sa.Column('parent_type', sa.String(30), nullable=True),
        sa.Column('parent_id', sa.String(36), nullable=True),
        sa.Column('correlation_id', sa.String(36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_lineage_node', 'knowledge_lineage_edges', ['node_type', 'node_id'])
    op.create_index('ix_lineage_parent', 'knowledge_lineage_edges', ['parent_type', 'parent_id'])

    # Best-effort backfill: give every pre-2.6 knowledge_object a manifest
    # row (defaults + its own known versions) so nothing is orphaned.
    op.execute("""
        INSERT INTO knowledge_manifests (
            id, knowledge_object_id, document_id, lifecycle_state, parser_name,
            parser_version, chunk_version, processing_version, schema_version,
            validation_status, correlation_id, created_at, updated_at
        )
        SELECT
            gen_random_uuid()::text, ko.id, ko.document_id, 'active', ko.doc_type,
            ko.parser_version, ko.chunk_version, ko.processing_version, ko.schema_version,
            'passed', gen_random_uuid()::text, ko.created_at, ko.created_at
        FROM knowledge_objects ko
        WHERE NOT EXISTS (
            SELECT 1 FROM knowledge_manifests km WHERE km.knowledge_object_id = ko.id
        )
    """)


def downgrade() -> None:
    op.drop_index('ix_lineage_parent', table_name='knowledge_lineage_edges')
    op.drop_index('ix_lineage_node', table_name='knowledge_lineage_edges')
    op.drop_table('knowledge_lineage_edges')

    op.drop_index('ix_knowledge_events_correlation', table_name='knowledge_events')
    op.drop_index('ix_knowledge_events_ko', table_name='knowledge_events')
    op.drop_table('knowledge_events')

    op.drop_index('ix_knowledge_manifests_doc', table_name='knowledge_manifests')
    op.drop_index('ix_knowledge_manifests_ko', table_name='knowledge_manifests')
    op.drop_table('knowledge_manifests')

    op.drop_column('document_processing_jobs', 'correlation_id')
