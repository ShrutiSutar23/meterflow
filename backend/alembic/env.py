# backend/alembic/env.py
"""
Alembic Migration Environment
================================
Alembic is the standard database migration tool for SQLAlchemy.
It tracks every schema change (like Git for your database).

WHY MIGRATIONS?
  Without migrations (create_all approach):
    - Running the app twice can cause errors on existing tables
    - Can't rename columns, add indexes, or change column types safely
    - Can't roll back a bad schema change
    - Multiple developers can't coordinate DB changes

  With Alembic migrations:
    - Every change is a versioned script: 001_initial.py → 002_add_orgs.py
    - Run: alembic upgrade head → applies all pending migrations
    - Run: alembic downgrade -1 → rolls back one migration
    - History: alembic history → shows all migrations applied

COMMANDS TO KNOW:
  # Initial setup (run once)
  pip install alembic
  alembic init alembic

  # Create a new migration after changing a model
  alembic revision --autogenerate -m "add stripe_customer_id to users"

  # Apply all pending migrations
  alembic upgrade head

  # Roll back the last migration
  alembic downgrade -1

  # See current migration version
  alembic current

  # See full migration history
  alembic history

ASYNC SUPPORT:
  SQLAlchemy 2.0 + asyncpg requires async migration support.
  We use run_async_migrations() with asyncio.run() below.
"""

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Load Alembic config ────────────────────────────────────────────────────────
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Import all models so Alembic can detect them ──────────────────────────────
# IMPORTANT: Every model file must be imported here.
# If you add a new model and forget to import it, Alembic won't track it.
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backend.config.database import Base
from backend.models.user_model import User                     # noqa
from backend.models.apikey_model import APIKey                 # noqa
from backend.models.billing_model import UsageRecord, Invoice  # noqa
from backend.models.organization_model import (               # noqa
    Organization, OrgMember, OrgInvite
)

# This is the metadata Alembic compares against your DB to find differences
target_metadata = Base.metadata

# ── Get DB URL from environment ────────────────────────────────────────────────
def get_url():
    from dotenv import load_dotenv
    load_dotenv()
    url = os.getenv("POSTGRES_URL", "")
    # Alembic needs postgresql:// not postgresql+asyncpg://
    return url.replace("postgresql+asyncpg://", "postgresql://")


# ── Offline migration (generates SQL without connecting) ──────────────────────
def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode — generates SQL script.
    Useful for reviewing changes before applying, or for DBs you can't connect to.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online migration (connects and applies directly) ──────────────────────────
def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations against a live database using asyncpg."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,    # Don't pool connections during migration
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
