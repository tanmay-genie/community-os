"""amenity enrichment — multi-instance discovery

Adds the columns needed for ARIA's amenity discovery flow:
  type        — canonical category ("gym", "pool", "court_badminton", ...).
                Indexed because find_amenities_by_type filters on every call.
  description — long human description shown on rich amenity cards.
  features    — JSON-encoded list of feature strings (Text on both SQLite
                and Postgres, deliberately avoiding JSONB to keep dev SQLite
                in lock-step with prod Postgres).
  image_url   — optional thumbnail URL (frontend falls back to a type icon
                if empty).
  block       — building block label ("A", "B", ..., or arbitrary string).
  floor       — floor label ("Ground Floor", "1st Floor", "Basement", ...).

Backfill rules for existing rows:
  - ``type`` is derived from ``name`` (e.g. "gym" -> "gym",
    "community hall" -> "hall", "badminton" -> "court_badminton",
    "tennis" -> "court_tennis", "clubhouse" -> "clubhouse",
    "pool" -> "pool"). Anything we cannot map cleanly stays as "other".
  - ``block`` and ``floor`` are best-effort parses of ``location``: we look
    for "Block X" and a floor keyword. Misses are left empty rather than
    risk a wrong guess.

Idempotency: each ALTER TABLE is wrapped in IF NOT EXISTS-style checks so
a partial migration can be re-run without error. SQLite branches use a
column-existence probe via PRAGMA because SQLite's ALTER TABLE doesn't
support IF NOT EXISTS.

Operational notes for dev SQLite installs:
  Dev runs typically use the in-memory SQLite fallback driven by
  ``aria.society.db.create_all_tables``. If a *file-backed* SQLite DB was
  used, the simplest path on dev machines is:

      1. Stop chat_api
      2. Delete the SQLite file (or DROP TABLE amenities; DROP TABLE bookings)
      3. Run: python -m aria.society.seed_amenities
      4. Start chat_api

  In production (Postgres):

      alembic upgrade head
      python -m aria.society.seed_amenities  # idempotent — safe to re-run

Revision ID: 0004_amenity_enrichment
Revises: 0003_add_llm_calls_metrics_table
Create Date: 2026-05-02 10:00:00.000000
"""
from __future__ import annotations

import re
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "0004_amenity_enrichment"
down_revision: Union[str, None] = "0003_add_llm_calls_metrics_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Helpers ────────────────────────────────────────────────────────────


def _is_sqlite(bind) -> bool:
    return bind.dialect.name == "sqlite"


def _column_exists(bind, table: str, column: str) -> bool:
    """Cross-dialect column-existence probe."""
    if _is_sqlite(bind):
        result = bind.execute(text(f"PRAGMA table_info({table})"))
        return any(row[1] == column for row in result)
    # Postgres
    result = bind.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column})
    return result.first() is not None


def _add_column_if_missing(bind, table: str, ddl_sql: str, column: str) -> None:
    if _column_exists(bind, table, column):
        return
    op.execute(ddl_sql)


def _name_to_type(raw_name: str) -> str:
    n = (raw_name or "").strip().lower()
    if not n:
        return "other"
    if "gym" in n:
        return "gym"
    if "pool" in n:
        return "pool"
    if "badminton" in n:
        return "court_badminton"
    if "tennis" in n:
        return "court_tennis"
    if "clubhouse" in n or "club house" in n:
        return "clubhouse"
    if "hall" in n:
        return "hall"
    if "studio" in n or "yoga" in n or "meditation" in n:
        return "studio"
    if "spa" in n or "wellness" in n or "sauna" in n:
        return "spa"
    if "library" in n or "reading" in n:
        return "library"
    return "other"


_BLOCK_RE = re.compile(r"block\s+([A-Za-z0-9]+)", re.IGNORECASE)
_FLOOR_RE = re.compile(
    r"(ground floor|basement|terrace|\d+(?:st|nd|rd|th)\s+floor)",
    re.IGNORECASE,
)


def _parse_location(loc: str) -> tuple[str, str]:
    """Best-effort (block, floor) extraction; both empty when we cannot guess."""
    if not loc:
        return "", ""
    block = ""
    floor = ""
    bm = _BLOCK_RE.search(loc)
    if bm:
        block = f"Block {bm.group(1).upper()}"
    fm = _FLOOR_RE.search(loc)
    if fm:
        floor = fm.group(1).title().replace("Floor", "Floor")
    return block, floor


# ── Upgrade / Downgrade ────────────────────────────────────────────────


def upgrade() -> None:
    bind = op.get_bind()
    sqlite = _is_sqlite(bind)

    text_type = "TEXT" if sqlite else "VARCHAR(500)"
    short_text = "TEXT" if sqlite else "VARCHAR(50)"

    _add_column_if_missing(
        bind, "amenities",
        f"ALTER TABLE amenities ADD COLUMN type VARCHAR(50) NOT NULL DEFAULT 'other'",
        "type",
    )
    _add_column_if_missing(
        bind, "amenities",
        "ALTER TABLE amenities ADD COLUMN description TEXT DEFAULT ''",
        "description",
    )
    _add_column_if_missing(
        bind, "amenities",
        "ALTER TABLE amenities ADD COLUMN features TEXT DEFAULT '[]'",
        "features",
    )
    _add_column_if_missing(
        bind, "amenities",
        f"ALTER TABLE amenities ADD COLUMN image_url {text_type} DEFAULT ''",
        "image_url",
    )
    _add_column_if_missing(
        bind, "amenities",
        f"ALTER TABLE amenities ADD COLUMN block {short_text} DEFAULT ''",
        "block",
    )
    _add_column_if_missing(
        bind, "amenities",
        f"ALTER TABLE amenities ADD COLUMN floor {short_text} DEFAULT ''",
        "floor",
    )

    # Index on type (skipped silently if already present)
    op.execute("CREATE INDEX IF NOT EXISTS ix_amenities_type ON amenities(type)")

    # Backfill existing rows. We deliberately only touch rows where the new
    # columns are still empty/default — re-runs are safe.
    rows = bind.execute(text(
        "SELECT amenity_id, name, location FROM amenities "
        "WHERE type = 'other' OR type IS NULL OR type = ''"
    )).fetchall()

    for row in rows:
        amenity_id, name, location = row[0], row[1], row[2] or ""
        guessed_type = _name_to_type(name)
        block, floor = _parse_location(location)
        bind.execute(
            text(
                "UPDATE amenities SET type = :t, block = :b, floor = :f "
                "WHERE amenity_id = :id"
            ),
            {"t": guessed_type, "b": block, "f": floor, "id": amenity_id},
        )


def downgrade() -> None:
    # Drop the index first so DROP COLUMN doesn't fail on Postgres.
    op.execute("DROP INDEX IF EXISTS ix_amenities_type")

    bind = op.get_bind()
    if _is_sqlite(bind):
        # SQLite < 3.35 cannot DROP COLUMN. Newer versions can. We try and
        # silently ignore failures — downgrade on dev SQLite usually means
        # "drop the file and re-create from baseline".
        for col in ("type", "description", "features", "image_url", "block", "floor"):
            try:
                op.execute(f"ALTER TABLE amenities DROP COLUMN {col}")
            except Exception:
                pass
        return

    for col in ("floor", "block", "image_url", "features", "description", "type"):
        op.execute(f"ALTER TABLE amenities DROP COLUMN IF EXISTS {col}")
