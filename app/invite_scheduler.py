"""Periodic resume of paused invite runs when pacing/FloodWait window ends (enqueue RQ jobs)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import BroadcastRun, InviteRun, utcnow
from app.queue import get_rq_queue, is_queue_enabled
from app.worker_jobs import execute_broadcast_run, execute_invite_run, get_worker_session_factory

logger = logging.getLogger(__name__)


def _parse_next_eligible_iso(raw: str) -> datetime | None:
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _invite_run_rq_timeout_seconds() -> int:
    raw = os.getenv("RQ_INVITE_TIMEOUT_SECONDS")
    if not raw:
        return 1800
    try:
        return max(1, int(raw))
    except ValueError:
        return 1800


def _broadcast_run_rq_timeout_seconds() -> int:
    raw = os.getenv("RQ_BROADCAST_TIMEOUT_SECONDS")
    if not raw:
        return 1800
    try:
        return max(1, int(raw))
    except ValueError:
        return 1800


def tick_invite_resume() -> int:
    """Set eligible paused invite runs to queued and enqueue worker jobs. Returns enqueue count."""
    if not is_queue_enabled():
        return 0

    session_factory = get_worker_session_factory()
    db = session_factory()
    enqueued = 0
    try:
        now = utcnow()
        runs = db.scalars(select(InviteRun).where(InviteRun.status == "paused")).all()
        to_queue: list[InviteRun] = []
        for run in runs:
            stats = run.stats if isinstance(run.stats, dict) else {}
            raw = stats.get("next_eligible_at")
            if not raw or not isinstance(raw, str):
                continue
            when = _parse_next_eligible_iso(raw)
            if when is None or when > now:
                continue
            pr = stats.get("pause_reason")
            if pr not in ("pacing_limit", "flood_wait"):
                continue
            to_queue.append(run)

        for run in to_queue:
            run.status = "queued"
            db.flush()

        db.commit()

        q = get_rq_queue()
        tout = _invite_run_rq_timeout_seconds()
        for run in to_queue:
            q.enqueue(
                execute_invite_run,
                run_id=run.id,
                job_timeout=tout,
            )
            enqueued += 1
        if enqueued:
            logger.info("invite_resume tick enqueued=%s", enqueued)
        return enqueued
    finally:
        db.close()


def tick_broadcast_resume() -> int:
    """Resume paused broadcast runs after pacing / FloodWait (enqueue RQ jobs)."""
    if not is_queue_enabled():
        return 0

    session_factory = get_worker_session_factory()
    db = session_factory()
    enqueued = 0
    try:
        now = utcnow()
        runs = db.scalars(select(BroadcastRun).where(BroadcastRun.status == "paused")).all()
        to_queue: list[BroadcastRun] = []
        for run in runs:
            stats = run.stats if isinstance(run.stats, dict) else {}
            raw = stats.get("next_eligible_at")
            if not raw or not isinstance(raw, str):
                continue
            when = _parse_next_eligible_iso(raw)
            if when is None or when > now:
                continue
            pr = stats.get("pause_reason")
            if pr not in ("pacing_limit", "flood_wait"):
                continue
            to_queue.append(run)

        for run in to_queue:
            run.status = "queued"
            db.flush()

        db.commit()

        q = get_rq_queue()
        tout = _broadcast_run_rq_timeout_seconds()
        for run in to_queue:
            q.enqueue(
                execute_broadcast_run,
                run_id=run.id,
                job_timeout=tout,
            )
            enqueued += 1
        if enqueued:
            logger.info("broadcast_resume tick enqueued=%s", enqueued)
        return enqueued
    finally:
        db.close()


def main() -> None:
    n_inv = tick_invite_resume()
    n_br = tick_broadcast_resume()
    print(f"invite_resume_enqueue={n_inv} broadcast_resume_enqueue={n_br}")


if __name__ == "__main__":
    main()
