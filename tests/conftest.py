from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, create_session_factory
from app.main import create_app
from app.models import Workspace
from app.telegram_client import DirectMessageSendResult, FloodWaitError, SourceTelegramMeta, TelegramClient, TgUser


@pytest.fixture(autouse=True)
def _app_encryption_key_autouse():
    if not os.environ.get("APP_ENCRYPTION_KEY"):
        os.environ["APP_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    yield


class FakeTelegramClient(TelegramClient):
    def __init__(self):
        self.invite_calls: list[tuple[str, int]] = []
        # (kind, peer, text) kind is "tg_user_id" | "username"
        self.dm_calls: list[tuple[str, int | str, str]] = []
        self._dm_message_seq = 0
        self.outbox_verify_fail_message_ids: set[int] = set()
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

    def supports_outbox_verify(self) -> bool:
        return True

    def send_direct_message(
        self,
        text: str,
        *,
        tg_user_id: int | None = None,
        username: str | None = None,
    ) -> DirectMessageSendResult:
        if (tg_user_id is None) == (username is None):
            raise ValueError("send_direct_message requires exactly one of tg_user_id or username")
        if tg_user_id is not None:
            self.dm_calls.append(("tg_user_id", int(tg_user_id), text))
            if int(tg_user_id) in self.flood_on_user_ids:
                raise FloodWaitError(60)
            self._dm_message_seq += 1
            return DirectMessageSendResult(message_id=self._dm_message_seq, out=True)
        un = str(username or "")
        self.dm_calls.append(("username", un, text))
        self._dm_message_seq += 1
        resolved = 888_000_000 + (abs(hash(un)) % 99_999_999)
        return DirectMessageSendResult(
            message_id=self._dm_message_seq,
            out=True,
            resolved_tg_user_id=resolved,
        )

    def verify_direct_message_outbox(
        self,
        message_id: int,
        *,
        tg_user_id: int | None = None,
        username: str | None = None,
    ) -> bool:
        _ = tg_user_id
        _ = username
        return int(message_id) not in self.outbox_verify_fail_message_ids

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

