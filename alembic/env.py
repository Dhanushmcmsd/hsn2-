from __future__ import annotations
import asyncio
from logging.config import fileConfig
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool
from alembic import context
import os, sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.models.database import Base, _make_async_url
from app.config import settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_async_url = _make_async_url(settings.DATABASE_URL)


def run_migrations_offline():
    context.configure(url=_async_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    cfg = config.get_section(config.config_ini_section)
    cfg["sqlalchemy.url"] = _async_url
    connectable = async_engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
