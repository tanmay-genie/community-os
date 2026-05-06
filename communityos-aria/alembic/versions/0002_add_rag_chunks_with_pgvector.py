"""add rag_chunks table with pgvector

Idempotent — safe to run on DBs without the vector extension
(the CREATE EXTENSION will simply be a no-op if the superuser
doesn't have permission or the extension isn't installed, in
which case the table is created with a TEXT column holding the
JSON-serialized embedding as a fallback).

Moved from t2t_backend/alembic during the T2T extraction. RAG
chunks are ARIA's own data, not T2T protocol data.

Revision ID: 0002_add_rag_chunks_with_pgvector
Revises: 0001_society_baseline
Create Date: 2026-04-23 09:29:22.666511
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_add_rag_chunks_with_pgvector"
down_revision: Union[str, None] = "0001_society_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBED_DIM = 384  # all-MiniLM-L6-v2


def upgrade() -> None:
    conn = op.get_bind()

    # Detect pgvector via savepoint so a failure doesn't poison the outer tx
    has_vector = False
    sp = conn.begin_nested()
    try:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        sp.commit()
        has_vector = True
    except Exception:
        sp.rollback()

    embed_col = f"embedding vector({EMBED_DIM})" if has_vector else "embedding TEXT"
    conn.execute(sa.text(f"""
        CREATE TABLE IF NOT EXISTS rag_chunks (
            chunk_id     TEXT PRIMARY KEY,
            doc_id       TEXT NOT NULL,
            source       TEXT NOT NULL,
            title        TEXT NOT NULL,
            text         TEXT NOT NULL,
            {embed_col},
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_rag_chunks_doc_id ON rag_chunks(doc_id)"))

    if has_vector:
        sp2 = conn.begin_nested()
        try:
            conn.execute(sa.text(
                "CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding "
                "ON rag_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
            ))
            sp2.commit()
        except Exception:
            sp2.rollback()


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rag_chunks")
