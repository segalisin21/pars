from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import CollectRun, InviteRun
from app.services import run_collect, run_invite
from app.telegram_client import TelegramClient


def execute_collect_run(*, db: Session, tg: TelegramClient, run_id: int) -> None:
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


def execute_invite_run(*, db: Session, tg: TelegramClient, run_id: int) -> None:
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

