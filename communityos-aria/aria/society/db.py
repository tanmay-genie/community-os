"""aria.society.db — Async SQLAlchemy engine and session factory for ARIA's society DB.

Owns the `Base` for all society tables (`amenities`, `bookings`,
`community_events`, `dues`, `community_notices`, `rsvps`). T2T no longer holds
these — they belong to ARIA, the society product.

Connects to the database identified by `settings.DATABASE_URL`. If the URL is
empty (e.g. dev without Postgres), a SQLite in-memory engine is used so unit
tests and local developer flows keep working.
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from aria.config import settings

logger = logging.getLogger(__name__)


def _resolve_url() -> str:
    url = (settings.DATABASE_URL or "").strip()
    if not url:
        logger.warning(
            "aria.society.db: DATABASE_URL not set — falling back to in-memory SQLite "
            "(society persistence will not survive process restart)"
        )
        return "sqlite+aiosqlite:///:memory:"
    return url


_DB_URL = _resolve_url()
_is_sqlite = _DB_URL.startswith("sqlite")

engine = create_async_engine(
    _DB_URL,
    echo=False,
    pool_pre_ping=not _is_sqlite,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for every society table."""


async def get_db() -> AsyncSession:
    """FastAPI dependency yielding an `AsyncSession` for society routes."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all_tables() -> None:
    """Create all society tables. Dev/test convenience — prefer Alembic in prod."""
    # Import so metadata is populated before create_all
    from aria.society import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("aria.society.db: tables created/verified")


async def dispose_engine() -> None:
    """Cleanly tear down the connection pool on shutdown."""
    await engine.dispose()
