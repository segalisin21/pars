from __future__ import annotations

from typing import Annotated

from fastapi import Header
from sqlalchemy.orm import Session, sessionmaker

from app.db import session_scope
from app.telegram_client import TelegramClient


def get_workspace_id(
    x_workspace_id: Annotated[int | None, Header(alias="X-Workspace-Id")] = None,
) -> int:
    """Resolves tenant scope; defaults to workspace 1 when header is omitted (local/tests)."""
    return 1 if x_workspace_id is None else int(x_workspace_id)


def get_db(session_factory: sessionmaker[Session]):
    def _get_db() -> Session:
        return next(session_scope(session_factory))

    return _get_db


def get_tg_client(tg_client: TelegramClient):
    def _get_tg() -> TelegramClient:
        return tg_client

    return _get_tg

