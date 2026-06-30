"""Add pinned and editable title features to conversations

Revision ID: 0003_conversation_features
Revises: 0002_firebase_auth
Create Date: 2026-06-30 20:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003_conversation_features'
down_revision: Union[str, None] = '0002_firebase_auth'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add is_pinned column
    op.add_column('conversations', sa.Column('is_pinned', sa.Boolean(), nullable=False, server_default='false'))
    
    # Add pin_order column (NULL for unpinned conversations)
    op.add_column('conversations', sa.Column('pin_order', sa.Integer(), nullable=True))
    
    # Create index for pinned conversations
    op.create_index('ix_conversations_pinned', 'conversations', ['user_id', 'is_pinned', 'pin_order'])


def downgrade() -> None:
    op.drop_index('ix_conversations_pinned', table_name='conversations')
    op.drop_column('conversations', 'pin_order')
    op.drop_column('conversations', 'is_pinned')
