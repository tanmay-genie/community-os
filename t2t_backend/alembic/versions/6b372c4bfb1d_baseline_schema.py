"""baseline schema

Represents the live DB schema as of initial Alembic adoption.
This is a no-op migration — use `alembic stamp head` on existing DBs
so future migrations diff from this point.

Revision ID: 6b372c4bfb1d
Revises:
Create Date: 2026-04-23 09:21:51.632100
"""
from typing import Sequence, Union

revision: str = "6b372c4bfb1d"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
