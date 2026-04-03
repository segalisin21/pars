"""Alembic migrations apply cleanly and are idempotent."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

from app.migration import upgrade_to_head


def test_alembic_upgrade_creates_tables_and_is_idempotent():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        # Windows: SQLite URL must use forward slashes (Path.as_posix).
        url = f"sqlite:///{Path(path).resolve().as_posix()}"
        upgrade_to_head(url)
        eng = create_engine(url)
        try:
            with eng.connect() as conn:
                assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                names = inspect(eng).get_table_names()
            assert "workspaces" in names
            assert "sources" in names
            # Second run: no error, still at head
            upgrade_to_head(url)
        finally:
            eng.dispose()
    finally:
        Path(path).unlink(missing_ok=True)
