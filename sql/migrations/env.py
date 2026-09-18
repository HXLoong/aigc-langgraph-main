"""Business database only; checkpoint migrations belong to AIOMySQLSaver."""
from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings


def run_sync(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(get_settings().business_mysql_uri, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_sync)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(dialect_name="mysql", literal_binds=True, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_online())
