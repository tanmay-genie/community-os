"""add llm_calls metrics table

Per-call telemetry for ARIA's LLM invocations (token counts, latency,
cost). Moved from t2t_backend/alembic during the T2T extraction — LLM
metrics belong to ARIA, not the T2T protocol layer.

Revision ID: 0003_add_llm_calls_metrics_table
Revises: 0002_add_rag_chunks_with_pgvector
Create Date: 2026-04-23 09:31:35.177452
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0003_add_llm_calls_metrics_table"
down_revision: Union[str, None] = "0002_add_rag_chunks_with_pgvector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS llm_calls (
            id              BIGSERIAL PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            twin_id         TEXT,
            model           TEXT NOT NULL,
            input_tokens    INTEGER NOT NULL DEFAULT 0,
            output_tokens   INTEGER NOT NULL DEFAULT 0,
            latency_ms      DOUBLE PRECISION NOT NULL DEFAULT 0,
            cost_usd        DOUBLE PRECISION NOT NULL DEFAULT 0,
            cached          BOOLEAN NOT NULL DEFAULT false,
            error           TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_llm_calls_conv    ON llm_calls(conversation_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_llm_calls_twin    ON llm_calls(twin_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_llm_calls_created ON llm_calls(created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS llm_calls")
