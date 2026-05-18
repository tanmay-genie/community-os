"""
auth/db.py — Async SQLAlchemy engine + session factory.
All modules import get_db from here.
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from config import settings


def _async_db_url(url: str) -> str:
    """Normalise a Postgres URL for use with SQLAlchemy's async engine.

    Render (and most managed Postgres providers) inject the bare
    ``postgresql://`` (or even ``postgres://``) scheme. SQLAlchemy's
    async engine needs the explicit ``+asyncpg`` driver suffix or it
    falls back to sync ``psycopg2`` and raises InvalidRequestError.
    """
    if not url:
        return url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    return url


engine = create_async_engine(
    _async_db_url(settings.DATABASE_URL),
    echo=settings.APP_ENV == "development",
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


async def get_db() -> AsyncSession:  # type: ignore[return]
    """FastAPI dependency — yields an async DB session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all_tables() -> None:
    """Create all tables on startup (dev only; use Alembic in prod)."""
    # Import all models so Base knows about them
    from auth.models import TwinModel  # noqa: F401
    from router.messages import MessageModel  # noqa: F401
    from audit.audit import EventModel  # noqa: F401
    from notifications.escalation import EscalationTaskModel  # noqa: F401
    from notifications.notifications import NotificationModel  # noqa: F401
    from policy.contracts import OrgContractModel  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
