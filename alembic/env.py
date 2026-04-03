"""Alembic environment: uses SQLAlchemy models from `app.models` for autogenerate."""

from __future__ import annotations

import os
from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context

from app.db import Base
import app.models  # noqa: F401 — register models on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    """Resolve DB URL.

    If `alembic.ini` / programmatic `Config.set_main_option` set a real URL (not the placeholder),
    that wins — so `upgrade_to_head(url)` is not overridden by unrelated `DATABASE_URL` in the environment.
    """
    main = config.get_main_option("sqlalchemy.url")
    if main and not main.startswith("driver://"):
        return main
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    return "sqlite:///./app.db"


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_url(), poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
