"""
Alembic async environment — wires t2t_backend models for autogenerate.

DB URL comes from t2t_backend.config.settings.DATABASE_URL (not alembic.ini),
so dev and prod share the same source of truth.
"""
import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Make t2t_backend importable when alembic is invoked from that dir
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth.db import Base  # noqa: E402
from config import settings  # noqa: E402

# Import every module containing a model so metadata is populated
import auth.models  # noqa: F401,E402
import router.messages  # noqa: F401,E402
import audit.audit  # noqa: F401,E402
import notifications.escalation  # noqa: F401,E402
import notifications.notifications  # noqa: F401,E402
import policy.contracts  # noqa: F401,E402

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
