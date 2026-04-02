from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, create_session_factory
from app.main import create_app
from app.models import Workspace
from app.telegram_client import FloodWaitError, SourceTelegramMeta, TelegramClient, TgUser


class FakeTelegramClient(TelegramClient):
    def __init__(self):
        self.invite_calls: list[tuple[str, int]] = []
        self.participants_by_source: dict[str, list[TgUser]] = {}
        self.message_senders_by_source: dict[str, list[TgUser]] = {}
        self.flood_on_user_ids: set[int] = set()
        self.source_meta_by_key: dict[str, SourceTelegramMeta] = {}

    def iter_participants(self, source_identifier: str):
        yield from list(self.participants_by_source.get(source_identifier, []))

    def iter_users_from_messages(self, source_identifier: str, *, limit=None, min_date=None):
        _ = min_date
        rows = list(self.message_senders_by_source.get(source_identifier, []))
        if limit is not None and limit > 0:
            rows = rows[:limit]
        yield from rows

    def get_participants(self, source_identifier: str) -> list[TgUser]:
        return list(self.iter_participants(source_identifier))

    def invite_to_target(self, target_identifier: str, tg_user_id: int) -> None:
        self.invite_calls.append((target_identifier, tg_user_id))
        if tg_user_id in self.flood_on_user_ids:
            raise FloodWaitError(60)

    def fetch_source_meta(self, source_identifier: str) -> SourceTelegramMeta | None:
        k = source_identifier.strip().removeprefix("@").lower()
        return self.source_meta_by_key.get(k)


@pytest.fixture()
def fake_tg():
    return FakeTelegramClient()


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    sf = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    db = sf()
    try:
        if db.get(Workspace, 1) is None:
            db.add(Workspace(id=1, name="default"))
        if db.get(Workspace, 2) is None:
            db.add(Workspace(id=2, name="other"))
        db.commit()
    finally:
        db.close()
    return sf


@pytest.fixture()
def client(session_factory, fake_tg):
    app = create_app(session_factory=session_factory, tg_client=fake_tg)
    return TestClient(app)

