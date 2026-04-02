from __future__ import annotations

import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import CollectRun, InviteRun
from app.services import process_collect_run, process_invite_run
from app.telegram_client import TelegramClient
from app.telethon_client import TelethonTelegramClient

logger = logging.getLogger(__name__)


def _tg_client_mode(tg: TelegramClient) -> str:
    return "telethon" if isinstance(tg, TelethonTelegramClient) else "noop"


def _get_session_factory() -> sessionmaker[Session]:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is required for worker jobs")
    engine = create_engine(
        db_url,
        future=True,
        pool_pre_ping=True,
        pool_recycle=300,
    )
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
            def iter_participants(self, source_identifier: str):
                return iter(())

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

        logger.info(
            "collect_run start run_id=%s source_ids=%s tg_client=%s",
            run_id,
            run.source_ids,
            _tg_client_mode(tg),
        )
        try:
            process_collect_run(db, tg, run)
        except Exception:
            run.status = "failed"
            logger.exception(
                "collect_run failed run_id=%s source_ids=%s tg_client=%s",
                run_id,
                run.source_ids,
                _tg_client_mode(tg),
            )
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

        logger.info(
            "invite_run start run_id=%s target_id=%s tg_client=%s",
            run_id,
            run.target_id,
            _tg_client_mode(tg),
        )
        try:
            process_invite_run(db, tg, run)
        except Exception:
            run.status = "failed"
            logger.exception(
                "invite_run failed run_id=%s target_id=%s tg_client=%s",
                run_id,
                run.target_id,
                _tg_client_mode(tg),
            )
            raise
        finally:
            db.commit()
    finally:
        db.close()

