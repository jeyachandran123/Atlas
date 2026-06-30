"""add firebase auth fields to user

Revision ID: 0002_firebase_auth
Revises: 0001_initial_schema
Create Date: 2024-01-15

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0002_firebase_auth'
down_revision = '0001_initial_schema'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add Firebase OAuth fields to users table
    op.add_column('users', sa.Column('auth_provider', sa.String(length=20), nullable=False, server_default='email'))
    op.add_column('users', sa.Column('firebase_uid', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('profile_picture_url', sa.String(length=500), nullable=True))
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), nullable=False, server_default='False'))
    
    # Add index on firebase_uid for faster lookups
    op.create_index('ix_users_firebase_uid', 'users', ['firebase_uid'], unique=False)
    
    # Make hashed_password nullable (not needed for OAuth users)
    op.alter_column('users', 'hashed_password',
               existing_type=sa.String(length=255),
               nullable=False,
               server_default='')


def downgrade() -> None:
    # Remove index
    op.drop_index('ix_users_firebase_uid', table_name='users')
    
    # Remove columns
    op.drop_column('users', 'email_verified')
    op.drop_column('users', 'profile_picture_url')
    op.drop_column('users', 'firebase_uid')
    op.drop_column('users', 'auth_provider')
    
    # Restore hashed_password as NOT NULL
    op.alter_column('users', 'hashed_password',
               existing_type=sa.String(length=255),
               nullable=False)
