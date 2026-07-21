"""DIP Phase 3 fix — ON DELETE CASCADE for embedding_events.job_id

Found during Phase 3 gating: deleting an embedding_jobs row via two
separate application-level DELETE statements (events, then jobs) leaves a
window where a concurrently-running embedding worker can commit a new
event for that same job between the two statements, causing a foreign key
violation. Moving the cascade into the database makes the delete atomic
and closes the race entirely — Postgres handles it as one operation.

No data loss: this only changes what happens when a PARENT embedding_jobs
row is deleted (which today only happens during a document reprocess wipe,
an already-intentional destructive operation); it does not delete anything
on its own.

Revision ID: 0011_embedding_events_cascade
Revises: 0010_semantic_platform
Create Date: 2026-07-21 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = '0011_embedding_events_cascade'
down_revision: Union[str, None] = '0010_semantic_platform'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('embedding_events_job_id_fkey', 'embedding_events', type_='foreignkey')
    op.create_foreign_key(
        'embedding_events_job_id_fkey', 'embedding_events', 'embedding_jobs',
        ['job_id'], ['id'], ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint('embedding_events_job_id_fkey', 'embedding_events', type_='foreignkey')
    op.create_foreign_key(
        'embedding_events_job_id_fkey', 'embedding_events', 'embedding_jobs',
        ['job_id'], ['id'],
    )
