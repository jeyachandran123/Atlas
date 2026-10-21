"""Customize → Plugins: plugin_connections.

Purely additive. Stores one row per (user, plugin) with the credential encrypted.

Revision ID: 0022_plugins
Revises: 0021_skills
Create Date: 2026-10-21 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_plugins"
down_revision: str | None = "0021_skills"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plugin_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plugin", sa.String(32), nullable=False),
        sa.Column("account", sa.String(255), nullable=False, server_default=""),
        sa.Column("scopes", sa.Text, nullable=False, server_default=""),
        sa.Column("secret_encrypted", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "plugin", name="uq_plugin_connections_user_plugin"),
    )
    op.create_index("ix_plugin_connections_user_id", "plugin_connections", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_plugin_connections_user_id", table_name="plugin_connections")
    op.drop_table("plugin_connections")
