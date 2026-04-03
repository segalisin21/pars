"""Run Alembic migrations on application startup (replaces `Base.metadata.create_all`)."""

from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)


def upgrade_to_head(database_url: str) -> None:
    """Apply all pending Alembic revisions up to `head`."""
    root = Path(__file__).resolve().parent.parent
    ini_path = root / "alembic.ini"
    if not ini_path.is_file():
        raise RuntimeError(f"Alembic config not found: {ini_path}")

    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", database_url)
    logger.info("Running Alembic migrations (upgrade head)")
    command.upgrade(cfg, "head")
