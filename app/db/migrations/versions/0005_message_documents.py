"""Add message_documents table for persistent document (PDF/Word/text) storage

Revision ID: 0005_message_documents
Revises: 0004_message_images
Create Date: 2026-07-18 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005_message_documents'
down_revision: Union[str, None] = '0004_message_images'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'message_documents',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('message_id', sa.String(36), sa.ForeignKey('messages.id'), nullable=False),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('conversations.id'), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('mime_type', sa.String(100), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('storage_path', sa.String(1000), nullable=False),
        sa.Column('text_path', sa.String(1000), nullable=False),
        sa.Column('doc_hash', sa.String(64), nullable=False),
        sa.Column('page_count', sa.Integer(), nullable=True),
        sa.Column('char_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_message_documents_msg', 'message_documents', ['message_id'])
    op.create_index('ix_message_documents_conv', 'message_documents', ['conversation_id'])


def downgrade() -> None:
    op.drop_index('ix_message_documents_conv', table_name='message_documents')
    op.drop_index('ix_message_documents_msg', table_name='message_documents')
    op.drop_table('message_documents')
