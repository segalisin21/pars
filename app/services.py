from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from time import monotonic

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    CandidateSourceLink,
    CandidateUser,
    CollectRun,
    InviteAttempt,
    InviteRun,
    InviteTarget,
    Source,
    SuppressionList,
    utcnow,
)
from app.telegram_client import FloodWaitError, TelegramClient, TgUser

logger = logging.getLogger(__name__)

# PostgreSQL INTEGER max; BIGINT is required for typical Telegram user ids.
_INT32_MAX = 2_147_483_647


def _int_env(name: str, default: int, *, min_value: int = 1, max_value: int | None = None) -> int:
    raw = os.getenv(name)
    if not raw:
        v = default
    else:
        try:
            v = int(raw)
        except ValueError:
            v = default
    v = max(min_value, v)
    if max_value is not None:
        v = min(max_value, v)
    return v


def normalize_username(username: str | None) -> str | None:
    if username is None:
        return None
    u = username.strip()
    if u.startswith("@"):
        u = u[1:]
    u = u.lower()
    return u or None


def upsert_candidate(db: Session, tg: TgUser) -> CandidateUser:
    username = normalize_username(tg.username)
    now = utcnow()

    existing: CandidateUser | None = None
    if tg.tg_user_id is not None:
        existing = db.scalar(select(CandidateUser).where(CandidateUser.tg_user_id == tg.tg_user_id))
    if existing is None and username is not None:
        existing = db.scalar(select(CandidateUser).where(CandidateUser.username == username))

    if existing is not None:
        existing.last_seen_at = now
        if existing.username is None and username is not None:
            existing.username = username
        if existing.display_name is None and tg.display_name:
            existing.display_name = tg.display_name
        if existing.tg_user_id is None and tg.tg_user_id is not None:
            existing.tg_user_id = tg.tg_user_id
        return existing

    candidate = CandidateUser(
        tg_user_id=tg.tg_user_id,
        username=username,
        display_name=tg.display_name,
        first_seen_at=now,
        last_seen_at=now,
    )
    # Use a SAVEPOINT so a unique-constraint collision does not rollback the whole outer transaction.
    try:
        with db.begin_nested():
            db.add(candidate)
            db.flush()
        return candidate
    except IntegrityError:
        if tg.tg_user_id is not None:
            existing = db.scalar(select(CandidateUser).where(CandidateUser.tg_user_id == tg.tg_user_id))
        if existing is None and username is not None:
            existing = db.scalar(select(CandidateUser).where(CandidateUser.username == username))
        if existing is None:
            raise
        existing.last_seen_at = now
        return existing


def link_candidate_to_source(db: Session, candidate_id: int, source_id: int) -> None:
    link = db.scalar(
        select(CandidateSourceLink).where(
            and_(CandidateSourceLink.candidate_id == candidate_id, CandidateSourceLink.source_id == source_id)
        )
    )
    if link is None:
        db.add(CandidateSourceLink(candidate_id=candidate_id, source_id=source_id))


def process_collect_run(db: Session, tg_client: TelegramClient, run: CollectRun) -> CollectRun:
    batch_size = _int_env("COLLECT_BATCH_SIZE", 300, min_value=1, max_value=5000)
    progress_every = _int_env("COLLECT_PROGRESS_EVERY", 500, min_value=1, max_value=50_000)

    run.status = "running"
    run.started_at = utcnow()
    run.finished_at = None
    if not isinstance(run.stats, dict):
        run.stats = {}
    db.flush()

    discovered_total = 0
    new_candidates = 0
    updated_candidates = 0
    last_commit_at = 0

    def _flush_progress(*, force: bool = False) -> None:
        nonlocal last_commit_at
        if not force and (discovered_total - last_commit_at) < batch_size:
            return
        run.stats = {
            "discovered_total": discovered_total,
            "new_candidates": new_candidates,
            "updated_candidates": updated_candidates,
            "skipped": 0,
        }
        db.flush()
        db.commit()
        last_commit_at = discovered_total

    for sid in run.source_ids:
        src = db.get(Source, sid)
        if src is None:
            raise KeyError(f"source_not_found:{sid}")
        if not src.enabled:
            continue

        for u in tg_client.iter_participants(src.identifier):
            discovered_total += 1
            before_id = None
            if u.tg_user_id is not None:
                existing = db.scalar(select(CandidateUser.id).where(CandidateUser.tg_user_id == u.tg_user_id))
                before_id = existing
            try:
                cand = upsert_candidate(db, u)
                link_candidate_to_source(db, cand.id, src.id)
            except DataError as e:
                uid = u.tg_user_id
                orig_name = type(e.orig).__name__ if e.orig else None
                logger.error(
                    "collect persist failed collect_run_id=%s source_id=%s "
                    "tg_user_id_exceeds_int32=%s db_error=%s",
                    run.id,
                    sid,
                    uid is not None and uid > _INT32_MAX,
                    orig_name,
                    exc_info=True,
                )
                raise
            if before_id is None and (u.tg_user_id is not None or normalize_username(u.username) is not None):
                if cand.first_seen_at == cand.last_seen_at:
                    new_candidates += 1
                else:
                    updated_candidates += 1

            if discovered_total % progress_every == 0:
                logger.info(
                    "collect progress collect_run_id=%s source_id=%s discovered_total=%s new=%s updated=%s",
                    run.id,
                    sid,
                    discovered_total,
                    new_candidates,
                    updated_candidates,
                )

            _flush_progress()

    run.status = "succeeded"
    run.finished_at = utcnow()
    run.stats = {
        "discovered_total": discovered_total,
        "new_candidates": new_candidates,
        "updated_candidates": updated_candidates,
        "skipped": 0,
    }
    db.flush()
    return run


def run_collect(db: Session, tg_client: TelegramClient, source_ids: list[int]) -> CollectRun:
    run = CollectRun(status="running", source_ids=source_ids, started_at=utcnow(), stats={})
    db.add(run)
    db.flush()
    return process_collect_run(db, tg_client, run)


def is_suppressed(db: Session, candidate: CandidateUser, now: datetime) -> bool:
    username = normalize_username(candidate.username)
    stmt = select(SuppressionList).where(
        or_(
            and_(SuppressionList.tg_user_id.is_not(None), SuppressionList.tg_user_id == candidate.tg_user_id),
            and_(SuppressionList.username.is_not(None), SuppressionList.username == username),
        )
    )
    rows = db.scalars(stmt).all()
    for r in rows:
        if r.until is None or r.until > now:
            return True
    return False


def process_invite_run(db: Session, tg_client: TelegramClient, run: InviteRun) -> InviteRun:
    run.status = "running"
    run.started_at = utcnow()
    run.finished_at = None
    if not isinstance(run.stats, dict):
        run.stats = {}
    db.flush()

    target_id = run.target_id
    policy = run.policy
    target = db.get(InviteTarget, target_id)
    if target is None:
        raise KeyError(f"target_not_found:{target_id}")
    if not target.enabled:
        raise ValueError("target_disabled")

    now = utcnow()
    cooldown_minutes = int(policy.get("cooldown_minutes", 1440))
    cooldown_since = now - timedelta(minutes=cooldown_minutes)

    attempted = success = skipped = failed = 0
    failed_by_code: dict[str, int] = {}

    max_per_minute = int(policy.get("max_per_minute", 2))
    max_per_hour = int(policy.get("max_per_hour", 30))
    window_min_start = monotonic()
    window_hour_start = monotonic()
    sent_in_min = 0
    sent_in_hour = 0

    candidates = db.scalars(select(CandidateUser).order_by(CandidateUser.id.asc())).all()
    for cand in candidates:
        if is_suppressed(db, cand, now):
            continue

        prev_success = db.scalar(
            select(func.count(InviteAttempt.id)).where(
                and_(
                    InviteAttempt.target_id == target_id,
                    InviteAttempt.candidate_id == cand.id,
                    InviteAttempt.status == "success",
                )
            )
        )
        if prev_success and prev_success > 0:
            continue

        recent_attempt = db.scalar(
            select(func.count(InviteAttempt.id)).where(
                and_(
                    InviteAttempt.target_id == target_id,
                    InviteAttempt.candidate_id == cand.id,
                    InviteAttempt.attempted_at >= cooldown_since,
                )
            )
        )
        if recent_attempt and recent_attempt > 0:
            continue

        attempted += 1
        if cand.tg_user_id is None:
            skipped += 1
            db.add(
                InviteAttempt(
                    invite_run_id=run.id,
                    target_id=target_id,
                    candidate_id=cand.id,
                    status="skipped",
                    error_code="missing_tg_user_id",
                    attempted_at=utcnow(),
                )
            )
            continue

        try:
            # Enforce simple pacing without sleeping: stop the run once limits are reached.
            now_m = monotonic()
            if now_m - window_min_start >= 60:
                window_min_start = now_m
                sent_in_min = 0
            if now_m - window_hour_start >= 3600:
                window_hour_start = now_m
                sent_in_hour = 0
            if sent_in_min >= max_per_minute or sent_in_hour >= max_per_hour:
                run.status = "paused"
                run.stats = {
                    "attempted": attempted,
                    "success": success,
                    "skipped": skipped,
                    "failed": failed,
                    "failed_by_code": failed_by_code,
                    "pause_reason": "pacing_limit",
                }
                db.flush()
                return run

            tg_client.invite_to_target(target.identifier, cand.tg_user_id)
            success += 1
            sent_in_min += 1
            sent_in_hour += 1
            db.add(
                InviteAttempt(
                    invite_run_id=run.id,
                    target_id=target_id,
                    candidate_id=cand.id,
                    status="success",
                    attempted_at=utcnow(),
                )
            )
        except FloodWaitError as e:
            failed += 1
            code = "flood_wait"
            failed_by_code[code] = failed_by_code.get(code, 0) + 1
            db.add(
                InviteAttempt(
                    invite_run_id=run.id,
                    target_id=target_id,
                    candidate_id=cand.id,
                    status="failed",
                    error_code=code,
                    attempted_at=utcnow(),
                )
            )
            # Safety-critical: stop processing further candidates.
            run.status = "paused"
            run.stats = {
                "attempted": attempted,
                "success": success,
                "skipped": skipped,
                "failed": failed,
                "failed_by_code": failed_by_code,
                "pause_reason": "flood_wait",
                "flood_wait_seconds": int(getattr(e, "seconds", 0)),
            }
            db.flush()
            return run
        except Exception:
            failed += 1
            code = "unknown"
            failed_by_code[code] = failed_by_code.get(code, 0) + 1
            db.add(
                InviteAttempt(
                    invite_run_id=run.id,
                    target_id=target_id,
                    candidate_id=cand.id,
                    status="failed",
                    error_code=code,
                    attempted_at=utcnow(),
                )
            )

    run.status = "succeeded"
    run.finished_at = utcnow()
    run.stats = {
        "attempted": attempted,
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "failed_by_code": failed_by_code,
    }
    return run


def run_invite(db: Session, tg_client: TelegramClient, target_id: int, policy: dict) -> InviteRun:
    run = InviteRun(status="running", target_id=target_id, policy=policy, started_at=utcnow(), stats={})
    db.add(run)
    db.flush()
    return process_invite_run(db, tg_client, run)

