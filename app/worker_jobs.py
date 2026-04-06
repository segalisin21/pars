from __future__ import annotations

import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.db import Base
from app.models import CollectRun, InviteRun, Source
from app.services import process_collect_run, process_invite_run, refresh_source_telegram_meta
from app.telegram_accounts_service import prepare_telegram_client_for_worker_run
from app.telegram_client import TelegramClient
from app.telethon_client import TelethonTelegramClient

logger = logging.getLogger(__name__)


def _tg_client_mode(tg: TelegramClient) -> str:
    return "telethon" if isinstance(tg, TelethonTelegramClient) else "noop"


def get_worker_session_factory() -> sessionmaker[Session]:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is required for worker jobs")
    # NullPool: one connection per checkout, no long-lived pool competing with the API service.
    engine = create_engine(
        db_url,
        future=True,
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False, autoflush=False)


def execute_collect_run(*, run_id: int) -> None:
    session_factory = get_worker_session_factory()
    db = session_factory()
    try:
        run = db.get(CollectRun, run_id)
        if run is None:
            return
        if run.status not in {"queued"}:
            return
        try:
            tg, _acc = prepare_telegram_client_for_worker_run(db, run, None)
        except Exception as e:
            logger.exception("collect_run telegram client failed run_id=%s", run_id)
            run.status = "failed"
            run.stats = {"error": {"code": "telegram_client_error", "message": str(e)}}
            db.commit()
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
            # Do not re-raise: we want the job to finish cleanly after persisting failure status/stats.
            return
        finally:
            db.commit()
    finally:
        db.close()


def execute_invite_run(*, run_id: int) -> None:
    session_factory = get_worker_session_factory()
    db = session_factory()
    try:
        run = db.get(InviteRun, run_id)
        if run is None:
            return
        if run.status not in {"queued"}:
            return
        try:
            tg, _acc = prepare_telegram_client_for_worker_run(db, run, None)
        except Exception as e:
            logger.exception("invite_run telegram client failed run_id=%s", run_id)
            run.status = "failed"
            run.stats = {"error": {"code": "telegram_client_error", "message": str(e)}}
            db.commit()
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
        finally:
            db.commit()
    finally:
        db.close()


def execute_refresh_source_meta(*, source_id: int, telegram_account_id: int | None = None) -> None:
    session_factory = get_worker_session_factory()
    db = session_factory()
    try:
        src = db.get(Source, source_id)
        if src is None:
            return
        class _Run:
            pass

        _r = _Run()
        _r.telegram_account_id = telegram_account_id
        try:
            tg, _acc = prepare_telegram_client_for_worker_run(db, _r, telegram_account_id)
        except Exception:
            logger.exception("refresh_source_meta telegram client failed source_id=%s", source_id)
            return
        refresh_source_telegram_meta(db, src.workspace_id, source_id, tg)
        db.commit()
        logger.info("refresh_source_meta done source_id=%s tg_client=%s", source_id, _tg_client_mode(tg))
    finally:
        db.close()

