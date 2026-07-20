"""DIP Phase 2 — knowledge objects, chunks, metadata, images, processing jobs/events

Revision ID: 0007_dip_knowledge
Revises: 0006_dip_documents
Create Date: 2026-07-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007_dip_knowledge'
down_revision: Union[str, None] = '0006_dip_documents'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column('processing_status', sa.String(20), nullable=False, server_default='none'),
    )

    op.create_table(
        'knowledge_objects',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('document_id', sa.String(36), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('title', sa.String(500), nullable=False, server_default=''),
        sa.Column('doc_type', sa.String(20), nullable=False),
        sa.Column('language', sa.String(10), nullable=False, server_default='unknown'),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('word_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('char_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('chunk_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('table_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('image_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('section_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('structure_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_knowledge_objects_doc', 'knowledge_objects', ['document_id'], unique=True)

    op.create_table(
        'document_chunks',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('document_id', sa.String(36), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('knowledge_object_id', sa.String(36), sa.ForeignKey('knowledge_objects.id'), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('token_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('node_type', sa.String(20), nullable=False, server_default='paragraph'),
        sa.Column('section_path', sa.String(1000), nullable=False, server_default=''),
        sa.Column('page', sa.Integer(), nullable=True),
        sa.Column('meta_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_document_chunks_doc_seq', 'document_chunks', ['document_id', 'seq'])
    op.create_index('ix_document_chunks_ko', 'document_chunks', ['knowledge_object_id'])

    op.create_table(
        'document_metadata',
        sa.Column('document_id', sa.String(36), sa.ForeignKey('documents.id'), primary_key=True),
        sa.Column('title', sa.String(500), nullable=False, server_default=''),
        sa.Column('author', sa.String(255), nullable=False, server_default=''),
        sa.Column('source_created', sa.String(50), nullable=False, server_default=''),
        sa.Column('source_modified', sa.String(50), nullable=False, server_default=''),
        sa.Column('language', sa.String(10), nullable=False, server_default='unknown'),
        sa.Column('page_count', sa.Integer(), nullable=True),
        sa.Column('sheet_count', sa.Integer(), nullable=True),
        sa.Column('slide_count', sa.Integer(), nullable=True),
        sa.Column('word_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('char_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('encoding', sa.String(30), nullable=False, server_default='utf-8'),
        sa.Column('custom_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        'document_images',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('document_id', sa.String(36), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('storage_key', sa.String(1000), nullable=False),
        sa.Column('name', sa.String(255), nullable=False, server_default=''),
        sa.Column('format', sa.String(10), nullable=False, server_default=''),
        sa.Column('page', sa.Integer(), nullable=True),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_document_images_doc', 'document_images', ['document_id'])

    op.create_table(
        'document_processing_jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('document_id', sa.String(36), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='queued'),
        sa.Column('current_stage', sa.String(30), nullable=False, server_default=''),
        sa.Column('attempt', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_doc_processing_jobs_doc', 'document_processing_jobs', ['document_id'])

    op.create_table(
        'document_processing_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('job_id', sa.String(36), sa.ForeignKey('document_processing_jobs.id'), nullable=False),
        sa.Column('document_id', sa.String(36), nullable=False),
        sa.Column('stage', sa.String(30), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('detail_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_doc_processing_events_job', 'document_processing_events', ['job_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_doc_processing_events_job', table_name='document_processing_events')
    op.drop_table('document_processing_events')
    op.drop_index('ix_doc_processing_jobs_doc', table_name='document_processing_jobs')
    op.drop_table('document_processing_jobs')
    op.drop_index('ix_document_images_doc', table_name='document_images')
    op.drop_table('document_images')
    op.drop_table('document_metadata')
    op.drop_index('ix_document_chunks_ko', table_name='document_chunks')
    op.drop_index('ix_document_chunks_doc_seq', table_name='document_chunks')
    op.drop_table('document_chunks')
    op.drop_index('ix_knowledge_objects_doc', table_name='knowledge_objects')
    op.drop_table('knowledge_objects')
    op.drop_column('documents', 'processing_status')
