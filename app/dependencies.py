from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from app.db import session_scope
from app.telegram_client import TelegramClient


def get_db(session_factory: sessionmaker[Session]):
    def _get_db() -> Session:
        return next(session_scope(session_factory))

    return _get_db


def get_tg_client(tg_client: TelegramClient):
    def _get_tg() -> TelegramClient:
        return tg_client

    return _get_tg

