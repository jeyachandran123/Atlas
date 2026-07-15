"""Add message_images table for persistent image storage

Revision ID: 0004_message_images
Revises: 0003_conversation_features
Create Date: 2026-07-01 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004_message_images'
down_revision: Union[str, None] = '0003_conversation_features'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'message_images',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('message_id', sa.String(36), sa.ForeignKey('messages.id'), nullable=False),
        sa.Column('conversation_id', sa.String(36), sa.ForeignKey('conversations.id'), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('mime_type', sa.String(50), nullable=False),
        sa.Column('size_bytes', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('storage_path', sa.String(1000), nullable=False),
        sa.Column('image_hash', sa.String(64), nullable=False),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_message_images_msg', 'message_images', ['message_id'])
    op.create_index('ix_message_images_conv', 'message_images', ['conversation_id'])


def downgrade() -> None:
    op.drop_index('ix_message_images_conv', table_name='message_images')
    op.drop_index('ix_message_images_msg', table_name='message_images')
    op.drop_table('message_images')
