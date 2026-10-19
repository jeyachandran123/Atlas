"""Customize → Skills: skills, skill_files, user_skill_settings,
user_skill_preferences, message_capabilities.

Purely additive. System skills are seeded at application startup (idempotent,
by checksum), not here, so the shipped SKILL.md files stay the source of truth.

Revision ID: 0018_skills
Revises: 0017_conv_retrieval_mode
Create Date: 2026-10-19 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_skills"
down_revision: str | None = "0017_conv_retrieval_mode"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "org_id",
            sa.String(36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "owner_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(1024), nullable=False),
        sa.Column("icon", sa.String(40), nullable=False, server_default="sparkles"),
        sa.Column("version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("triggers_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("modes_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("source_ref", sa.String(1000), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "scope", "org_id", "owner_user_id", "slug", name="uq_skills_scope_slug"
        ),
    )
    op.create_index(
        "uq_skills_system_slug",
        "skills",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("scope = 'system'"),
    )
    op.create_index(
        "uq_skills_org_slug",
        "skills",
        ["org_id", "slug"],
        unique=True,
        postgresql_where=sa.text("scope = 'org'"),
    )
    op.create_index("ix_skills_org", "skills", ["org_id"])
    op.create_index("ix_skills_owner", "skills", ["owner_user_id"])

    op.create_table(
        "skill_files",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "skill_id",
            sa.String(36),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("path", sa.String(255), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("size", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("skill_id", "path", name="uq_skill_files_path"),
    )

    op.create_table(
        "user_skill_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "skill_id",
            sa.String(36),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("pinned", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "skill_id", name="uq_user_skill"),
    )

    op.create_table(
        "user_skill_preferences",
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("auto_select", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("max_active", sa.Integer, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "message_capabilities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "message_id",
            sa.String(36),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "turn_id",
            sa.String(36),
            sa.ForeignKey("dip_conversation_turns.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("ref", sa.String(200), nullable=False),
        sa.Column("label", sa.String(200), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_message_capabilities_message", "message_capabilities", ["message_id"])
    op.create_index("ix_message_capabilities_turn", "message_capabilities", ["turn_id"])


def downgrade() -> None:
    op.drop_index("ix_message_capabilities_turn", table_name="message_capabilities")
    op.drop_index("ix_message_capabilities_message", table_name="message_capabilities")
    op.drop_table("message_capabilities")
    op.drop_table("user_skill_preferences")
    op.drop_table("user_skill_settings")
    op.drop_table("skill_files")
    op.drop_index("ix_skills_owner", table_name="skills")
    op.drop_index("ix_skills_org", table_name="skills")
    op.drop_index("uq_skills_org_slug", table_name="skills")
    op.drop_index("uq_skills_system_slug", table_name="skills")
    op.drop_table("skills")
