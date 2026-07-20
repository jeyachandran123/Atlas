"""Document Intelligence Platform Phase 1 — documents metadata table

Binary content lives in blob storage (S3); this table is metadata only.

Revision ID: 0006_dip_documents
Revises: 0005_message_documents
Create Date: 2026-07-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006_dip_documents'
down_revision: Union[str, None] = '0005_message_documents'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'documents',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('org_id', sa.String(36), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('uploaded_by', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('stored_filename', sa.String(255), nullable=False),
        sa.Column('extension', sa.String(20), nullable=False),
        sa.Column('mime_type', sa.String(100), nullable=False),
        sa.Column('size_bytes', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('checksum_sha256', sa.String(64), nullable=False),
        sa.Column('storage_provider', sa.String(20), nullable=False),
        sa.Column('storage_bucket', sa.String(255), nullable=True),
        sa.Column('storage_key', sa.String(1000), nullable=False),
        sa.Column('upload_status', sa.String(20), nullable=False, server_default='uploading'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('tags_json', sa.Text(), nullable=True),
        sa.Column('meta_json', sa.Text(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_documents_owner_created', 'documents', ['uploaded_by', 'created_at'])
    op.create_index('ix_documents_owner_checksum', 'documents', ['uploaded_by', 'checksum_sha256'])
    op.create_index('ix_documents_filename', 'documents', ['original_filename'])
    op.create_index('ix_documents_status', 'documents', ['upload_status'])


def downgrade() -> None:
    op.drop_index('ix_documents_status', table_name='documents')
    op.drop_index('ix_documents_filename', table_name='documents')
    op.drop_index('ix_documents_owner_checksum', table_name='documents')
    op.drop_index('ix_documents_owner_created', table_name='documents')
    op.drop_table('documents')
