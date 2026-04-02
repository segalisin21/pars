from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import CollectRun, InviteRun
from app.services import run_collect, run_invite
from app.telegram_client import TelegramClient
from app.telethon_client import TelethonTelegramClient


def _get_session_factory() -> sessionmaker[Session]:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is required for worker jobs")
    engine = create_engine(db_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False, autoflush=False)


def _get_tg_client() -> TelegramClient:
    # In Railway worker we expect a real Telegram session.
    # If env vars are missing, fall back to a noop client to keep jobs from crashing,
    # but collection will return 0 participants.
    try:
        return TelethonTelegramClient.from_env()
    except Exception:
        class _NoopTelegramClient(TelegramClient):
            def get_participants(self, source_identifier: str):
                return []

            def invite_to_target(self, target_identifier: str, tg_user_id: int) -> None:
                return None

        return _NoopTelegramClient()


def execute_collect_run(*, run_id: int) -> None:
    session_factory = _get_session_factory()
    tg = _get_tg_client()
    db = session_factory()
    try:
        run = db.get(CollectRun, run_id)
        if run is None:
            return
        if run.status not in {"queued"}:
            return
        run.status = "running"
        db.flush()

        try:
            run_collect(db, tg, run.source_ids)
        except Exception:
            run.status = "failed"
            raise
        finally:
            db.commit()
    finally:
        db.close()


def execute_invite_run(*, run_id: int) -> None:
    session_factory = _get_session_factory()
    tg = _get_tg_client()
    db = session_factory()
    try:
        run = db.get(InviteRun, run_id)
        if run is None:
            return
        if run.status not in {"queued"}:
            return
        run.status = "running"
        db.flush()

        try:
            run_invite(db, tg, run.target_id, run.policy)
        except Exception:
            run.status = "failed"
            raise
        finally:
            db.commit()
    finally:
        db.close()

