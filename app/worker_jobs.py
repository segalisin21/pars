from __future__ import annotations

import logging
import os
from datetime import timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.db import Base
from app.models import BroadcastRun, CollectRun, InviteRun, Source, TargetingProfile, TargetingRun, TargetingRunLog, TelegramAccount, utcnow
from app.services import (
    process_broadcast_run,
    process_collect_run,
    process_invite_run,
    refresh_source_telegram_meta,
)
from app.targeting_ai import capture_messages_for_workspace, recompute_features_for_profile
from app.targeting_params import TargetingParamsV2
from app.telegram_accounts_service import prepare_telegram_client_for_worker_run, telethon_client_for_account
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


def execute_broadcast_run(*, run_id: int) -> None:
    session_factory = get_worker_session_factory()
    db = session_factory()
    try:
        run = db.get(BroadcastRun, run_id)
        if run is None:
            return
        if run.status not in {"queued"}:
            return
        try:
            tg, _acc = prepare_telegram_client_for_worker_run(db, run, None)
        except Exception as e:
            logger.exception("broadcast_run telegram client failed run_id=%s", run_id)
            run.status = "failed"
            run.stats = {"error": {"code": "telegram_client_error", "message": str(e)}}
            db.commit()
            return

        run.status = "running"
        db.flush()

        logger.info(
            "broadcast_run start run_id=%s message_key=%s tg_client=%s",
            run_id,
            getattr(run, "message_key", ""),
            _tg_client_mode(tg),
        )
        try:
            process_broadcast_run(db, tg, run)
        except Exception:
            run.status = "failed"
            logger.exception(
                "broadcast_run failed run_id=%s message_key=%s tg_client=%s",
                run_id,
                getattr(run, "message_key", ""),
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


def _tr_log(db: Session, run: TargetingRun, msg: str) -> None:
    db.add(TargetingRunLog(workspace_id=run.workspace_id, run_id=run.id, msg=msg[:512]))


def execute_targeting_run(*, run_id: int) -> None:
    session_factory = get_worker_session_factory()
    db = session_factory()
    try:
        run = db.get(TargetingRun, run_id)
        if run is None:
            return
        if run.status not in {"queued"}:
            return

        profile = db.get(TargetingProfile, run.profile_id)
        if profile is None or profile.workspace_id != run.workspace_id:
            run.status = "failed"
            run.stage = "failed"
            run.error = {"code": "profile_not_found", "message": "Targeting profile not found"}
            run.updated_at = utcnow()
            run.finished_at = utcnow()
            db.commit()
            return

        # Telegram client (for capture). Use worker's configured account selection.
        class _Run:
            pass

        _r = _Run()
        _r.telegram_account_id = None
        try:
            tg, _acc = prepare_telegram_client_for_worker_run(db, _r, None)
        except Exception as e:
            logger.exception("targeting_run telegram client failed run_id=%s", run_id)
            run.status = "failed"
            run.stage = "failed"
            run.error = {"code": "telegram_client_error", "message": str(e)}
            run.updated_at = utcnow()
            run.finished_at = utcnow()
            db.commit()
            return

        run.status = "running"
        run.stage = "capture_messages"
        run.started_at = utcnow()
        run.updated_at = utcnow()
        run.progress = {"inserted_messages": 0, "upserted_candidates": 0}
        db.flush()
        _tr_log(db, run, "started")
        db.commit()

        params_raw = profile.params if isinstance(profile.params, dict) else {}
        try:
            v2 = TargetingParamsV2.model_validate(params_raw)
        except Exception as e:
            run.status = "failed"
            run.stage = "failed"
            run.error = {"code": "invalid_profile_params", "message": str(e)}
            run.updated_at = utcnow()
            run.finished_at = utcnow()
            _tr_log(db, run, "failed: invalid_profile_params")
            db.commit()
            return

        # Stage 1: capture messages
        min_date = (utcnow() - timedelta(days=int(v2.limits.days))).astimezone(timezone.utc)
        _tr_log(db, run, f"capture_messages: days={v2.limits.days} max_messages_per_source={v2.limits.max_messages_per_source}")
        inserted = capture_messages_for_workspace(
            db,
            tg,
            workspace_id=run.workspace_id,
            min_date=min_date,
            max_messages_per_source=int(v2.limits.max_messages_per_source),
        )
        run.progress = {**(run.progress or {}), "inserted_messages": int(inserted)}
        run.updated_at = utcnow()
        db.commit()

        # Stage 2: embed + score
        run.stage = "embed_and_score"
        run.updated_at = utcnow()
        _tr_log(db, run, "embed_and_score: start")
        db.commit()

        up = recompute_features_for_profile(db, workspace_id=run.workspace_id, profile=profile)
        run.progress = {**(run.progress or {}), "upserted_candidates": int(up)}
        run.stage = "done"
        run.status = "succeeded"
        run.updated_at = utcnow()
        run.finished_at = utcnow()
        _tr_log(db, run, "done")
        db.commit()
    finally:
        db.close()


def execute_spambot_check(*, account_id: int) -> None:
    session_factory = get_worker_session_factory()
    db = session_factory()
    try:
        acc = db.get(TelegramAccount, account_id)
        if acc is None:
            return
        if not acc.enabled:
            acc.spambot_error = "disabled"
            db.commit()
            return
        try:
            tg = telethon_client_for_account(db, account_id)
        except Exception as e:
            logger.exception("spambot telegram client failed account_id=%s", account_id)
            acc.spambot_error = str(e)
            db.commit()
            return

        ok, text, err = tg.fetch_spambot_status()
        if ok:
            acc.spambot_status_text = text
            acc.spambot_error = None
            acc.spambot_checked_at = utcnow()
        else:
            acc.spambot_error = err or "failed"
            acc.spambot_checked_at = utcnow()
        db.commit()
    finally:
        db.close()

