"""DIP Phase 3 fix — ON DELETE CASCADE for the remaining semantic-layer FKs
into the frozen Knowledge Platform tables.

0011 closed the embedding_jobs -> embedding_events race. Gating this phase's
E2E suite further exposed the same class of race one layer over: a
document reprocess wipe running in document_worker.py (one process) can
overlap with an in-flight embedding_worker.py run (a separate process)
for the same knowledge_id. No sequence of application-level DELETE
statements in one process can fully close a race against inserts
happening concurrently in a different process — only the database can,
by making the frozen pipeline's own document_chunks/knowledge_objects
deletes cascade automatically into the semantic layer as a single atomic
operation, regardless of what the other process is doing.

This makes wipe_all_semantic_for_document_reprocess() a defense-in-depth
belt (fast, no-op-if-nothing-there cleanup) rather than the sole
correctness guarantee — the belt-and-suspenders is the database cascade.

Revision ID: 0012_semantic_fk_cascade
Revises: 0011_embedding_events_cascade
Create Date: 2026-07-21 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = '0012_semantic_fk_cascade'
down_revision: Union[str, None] = '0011_embedding_events_cascade'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('embedding_jobs_knowledge_id_fkey', 'embedding_jobs', type_='foreignkey')
    op.create_foreign_key(
        'embedding_jobs_knowledge_id_fkey', 'embedding_jobs', 'knowledge_objects',
        ['knowledge_id'], ['id'], ondelete='CASCADE',
    )

    op.drop_constraint('embedding_records_knowledge_id_fkey', 'embedding_records', type_='foreignkey')
    op.create_foreign_key(
        'embedding_records_knowledge_id_fkey', 'embedding_records', 'knowledge_objects',
        ['knowledge_id'], ['id'], ondelete='CASCADE',
    )

    op.drop_constraint('embedding_records_chunk_id_fkey', 'embedding_records', type_='foreignkey')
    op.create_foreign_key(
        'embedding_records_chunk_id_fkey', 'embedding_records', 'document_chunks',
        ['chunk_id'], ['id'], ondelete='CASCADE',
    )

    op.drop_constraint('semantic_manifests_knowledge_id_fkey', 'semantic_manifests', type_='foreignkey')
    op.create_foreign_key(
        'semantic_manifests_knowledge_id_fkey', 'semantic_manifests', 'knowledge_objects',
        ['knowledge_id'], ['id'], ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint('semantic_manifests_knowledge_id_fkey', 'semantic_manifests', type_='foreignkey')
    op.create_foreign_key(
        'semantic_manifests_knowledge_id_fkey', 'semantic_manifests', 'knowledge_objects',
        ['knowledge_id'], ['id'],
    )

    op.drop_constraint('embedding_records_chunk_id_fkey', 'embedding_records', type_='foreignkey')
    op.create_foreign_key(
        'embedding_records_chunk_id_fkey', 'embedding_records', 'document_chunks',
        ['chunk_id'], ['id'],
    )

    op.drop_constraint('embedding_records_knowledge_id_fkey', 'embedding_records', type_='foreignkey')
    op.create_foreign_key(
        'embedding_records_knowledge_id_fkey', 'embedding_records', 'knowledge_objects',
        ['knowledge_id'], ['id'],
    )

    op.drop_constraint('embedding_jobs_knowledge_id_fkey', 'embedding_jobs', type_='foreignkey')
    op.create_foreign_key(
        'embedding_jobs_knowledge_id_fkey', 'embedding_jobs', 'knowledge_objects',
        ['knowledge_id'], ['id'],
    )
