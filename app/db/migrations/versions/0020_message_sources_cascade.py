"""Web search — message_sources rows die with their message.

Deleting a conversation, editing a prompt and deleting a message all delete
message rows, and each one returned 500 as soon as an answer had sources: the
foreign key was NO ACTION, so the database refused while the source rows still
pointed at the message.

The existing child tables (message_images, message_documents) are cleared by
hand at each call site instead. That is what failed here — three sites, and
nothing makes a fourth one remember. A source is worthless without the answer
it belongs to, so the database now removes them itself and no caller can get
this wrong again.

Revision ID: 0020_message_sources_cascade
Revises: 0019_message_source_images
Create Date: 2026-09-21 09:55:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = '0020_message_sources_cascade'
down_revision: str | None = '0019_message_source_images'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = 'message_sources_message_id_fkey'


def upgrade() -> None:
    op.drop_constraint(_FK, 'message_sources', type_='foreignkey')
    op.create_foreign_key(
        _FK, 'message_sources', 'messages',
        ['message_id'], ['id'], ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint(_FK, 'message_sources', type_='foreignkey')
    op.create_foreign_key(_FK, 'message_sources', 'messages', ['message_id'], ['id'])
