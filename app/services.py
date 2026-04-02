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


def _collect_mode() -> str:
    v = (os.getenv("COLLECT_MODE") or "participants").strip().lower()
    if v in {"participants", "messages", "both", "auto"}:
        return v
    return "participants"


def _collect_user_dedupe_key(u: TgUser) -> object:
    if u.tg_user_id is not None:
        return ("i", int(u.tg_user_id))
    uname = normalize_username(u.username)
    if uname is not None:
        return ("n", uname)
    return ("e", id(u))


def normalize_username(username: str | None) -> str | None:
    if username is None:
        return None
    u = username.strip()
    if u.startswith("@"):
        u = u[1:]
    u = u.lower()
    return u or None


def upsert_candidate(db: Session, workspace_id: int, tg: TgUser) -> CandidateUser:
    username = normalize_username(tg.username)
    now = utcnow()

    existing: CandidateUser | None = None
    if tg.tg_user_id is not None:
        existing = db.scalar(
            select(CandidateUser).where(
                CandidateUser.workspace_id == workspace_id,
                CandidateUser.tg_user_id == tg.tg_user_id,
            )
        )
    if existing is None and username is not None:
        existing = db.scalar(
            select(CandidateUser).where(
                CandidateUser.workspace_id == workspace_id,
                CandidateUser.username == username,
            )
        )

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
        workspace_id=workspace_id,
        tg_user_id=tg.tg_user_id,
        username=username,
        display_name=tg.display_name,
        first_seen_at=now,
        last_seen_at=now,
    )
    try:
        with db.begin_nested():
            db.add(candidate)
            db.flush()
        return candidate
    except IntegrityError:
        if tg.tg_user_id is not None:
            existing = db.scalar(
                select(CandidateUser).where(
                    CandidateUser.workspace_id == workspace_id,
                    CandidateUser.tg_user_id == tg.tg_user_id,
                )
            )
        if existing is None and username is not None:
            existing = db.scalar(
                select(CandidateUser).where(
                    CandidateUser.workspace_id == workspace_id,
                    CandidateUser.username == username,
                )
            )
        if existing is None:
            raise
        existing.last_seen_at = now
        return existing


def _find_existing_candidate_id(db: Session, workspace_id: int, u: TgUser) -> int | None:
    if u.tg_user_id is not None:
        cid = db.scalar(
            select(CandidateUser.id).where(
                CandidateUser.workspace_id == workspace_id,
                CandidateUser.tg_user_id == u.tg_user_id,
            )
        )
        if cid is not None:
            return int(cid)
    uname = normalize_username(u.username)
    if uname is not None:
        cid = db.scalar(
            select(CandidateUser.id).where(
                CandidateUser.workspace_id == workspace_id,
                CandidateUser.username == uname,
            )
        )
        if cid is not None:
            return int(cid)
    return None


def link_candidate_to_source(db: Session, workspace_id: int, candidate_id: int, source_id: int) -> bool:
    link = db.scalar(
        select(CandidateSourceLink).where(
            and_(
                CandidateSourceLink.workspace_id == workspace_id,
                CandidateSourceLink.candidate_id == candidate_id,
                CandidateSourceLink.source_id == source_id,
            )
        )
    )
    if link is None:
        db.add(
            CandidateSourceLink(
                workspace_id=workspace_id,
                candidate_id=candidate_id,
                source_id=source_id,
            )
        )
        return True
    return False


def process_collect_run(db: Session, tg_client: TelegramClient, run: CollectRun) -> CollectRun:
    workspace_id = run.workspace_id
    batch_size = _int_env("COLLECT_BATCH_SIZE", 300, min_value=1, max_value=5000)
    progress_every = _int_env("COLLECT_PROGRESS_EVERY", 500, min_value=1, max_value=50_000)
    collect_mode = _collect_mode()
    message_scan_limit = _int_env("COLLECT_MESSAGE_SCAN_LIMIT", 5000, min_value=1, max_value=500_000)

    run.status = "running"
    run.started_at = utcnow()
    run.finished_at = None
    if not isinstance(run.stats, dict):
        run.stats = {}
    db.flush()

    discovered_total = 0
    discovered_from_participants = 0
    discovered_from_messages = 0
    new_candidates = 0
    updated_candidates = 0
    last_commit_at = 0
    by_source_id: dict[str, dict[str, int]] = {}

    def _flush_progress(*, force: bool = False) -> None:
        nonlocal last_commit_at
        if not force and (discovered_total - last_commit_at) < batch_size:
            return
        run.stats = {
            "discovered_total": discovered_total,
            "discovered_from_participants": discovered_from_participants,
            "discovered_from_messages": discovered_from_messages,
            "collect_mode": collect_mode,
            "new_candidates": new_candidates,
            "updated_candidates": updated_candidates,
            "skipped": 0,
            "by_source_id": by_source_id,
        }
        db.flush()
        db.commit()
        last_commit_at = discovered_total

    def _ingest_user(u: TgUser, sk: str, source_id: int, channel: str) -> None:
        nonlocal discovered_total, new_candidates, updated_candidates
        nonlocal discovered_from_participants, discovered_from_messages

        if channel == "participants":
            discovered_from_participants += 1
            by_source_id[sk]["discovered_participants"] += 1
        else:
            discovered_from_messages += 1
            by_source_id[sk]["discovered_messages"] += 1
        by_source_id[sk]["discovered"] = (
            by_source_id[sk]["discovered_participants"] + by_source_id[sk]["discovered_messages"]
        )
        discovered_total += 1

        before_cand_id = _find_existing_candidate_id(db, workspace_id, u)
        try:
            cand = upsert_candidate(db, workspace_id, u)
            link_new = link_candidate_to_source(db, workspace_id, cand.id, source_id)
        except DataError as e:
            uid = u.tg_user_id
            orig_name = type(e.orig).__name__ if e.orig else None
            logger.error(
                "collect persist failed collect_run_id=%s source_id=%s "
                "tg_user_id_exceeds_int32=%s db_error=%s",
                run.id,
                source_id,
                uid is not None and uid > _INT32_MAX,
                orig_name,
                exc_info=True,
            )
            raise
        if link_new:
            by_source_id[sk]["new_source_links"] += 1
        has_id = u.tg_user_id is not None or normalize_username(u.username) is not None
        if has_id:
            if before_cand_id is None:
                new_candidates += 1
                by_source_id[sk]["new_candidates"] += 1
            else:
                updated_candidates += 1
                by_source_id[sk]["updated_candidates"] += 1

        if discovered_total % progress_every == 0:
            logger.info(
                "collect progress collect_run_id=%s source_id=%s discovered_total=%s new=%s updated=%s",
                run.id,
                source_id,
                discovered_total,
                new_candidates,
                updated_candidates,
            )

        _flush_progress()

    for sid in run.source_ids:
        src = db.get(Source, sid)
        if src is None:
            raise KeyError(f"source_not_found:{sid}")
        if src.workspace_id != workspace_id:
            raise KeyError(f"source_not_found:{sid}")
        if not src.enabled:
            continue

        sk = str(sid)
        by_source_id[sk] = {
            "discovered": 0,
            "discovered_participants": 0,
            "discovered_messages": 0,
            "new_candidates": 0,
            "updated_candidates": 0,
            "new_source_links": 0,
        }

        seen: set[object] = set()
        participant_rows = 0

        if collect_mode in {"participants", "both", "auto"}:
            for u in tg_client.iter_participants(src.identifier):
                participant_rows += 1
                seen.add(_collect_user_dedupe_key(u))
                _ingest_user(u, sk, sid, "participants")

        run_messages = (
            collect_mode in {"messages", "both"}
            or (collect_mode == "auto" and participant_rows == 0)
        )

        if run_messages:
            for u in tg_client.iter_users_from_messages(
                src.identifier,
                limit=message_scan_limit,
                min_date=None,
            ):
                key = _collect_user_dedupe_key(u)
                if key in seen:
                    continue
                seen.add(key)
                _ingest_user(u, sk, sid, "messages")

    run.status = "succeeded"
    run.finished_at = utcnow()
    run.stats = {
        "discovered_total": discovered_total,
        "discovered_from_participants": discovered_from_participants,
        "discovered_from_messages": discovered_from_messages,
        "collect_mode": collect_mode,
        "new_candidates": new_candidates,
        "updated_candidates": updated_candidates,
        "skipped": 0,
        "by_source_id": by_source_id,
    }
    db.flush()
    return run


def refresh_source_telegram_meta(
    db: Session,
    workspace_id: int,
    source_id: int,
    tg_client: TelegramClient,
) -> Source | None:
    src = db.get(Source, source_id)
    if src is None or src.workspace_id != workspace_id:
        return None
    meta = tg_client.fetch_source_meta(src.identifier)
    if meta is None:
        return src
    src.telegram_title = meta.title
    src.telegram_participants_count = meta.participants_count
    src.telegram_meta_updated_at = utcnow()
    db.flush()
    return src


def run_collect(db: Session, tg_client: TelegramClient, source_ids: list[int], workspace_id: int) -> CollectRun:
    run = CollectRun(
        workspace_id=workspace_id,
        status="running",
        source_ids=source_ids,
        started_at=utcnow(),
        stats={},
    )
    db.add(run)
    db.flush()
    return process_collect_run(db, tg_client, run)


def is_suppressed(db: Session, workspace_id: int, candidate: CandidateUser, now: datetime) -> bool:
    username = normalize_username(candidate.username)
    stmt = select(SuppressionList).where(SuppressionList.workspace_id == workspace_id).where(
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
    workspace_id = run.workspace_id
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
    if target.workspace_id != workspace_id:
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

    candidates = db.scalars(
        select(CandidateUser)
        .where(CandidateUser.workspace_id == workspace_id)
        .order_by(CandidateUser.id.asc())
    ).all()
    for cand in candidates:
        if is_suppressed(db, workspace_id, cand, now):
            continue

        prev_success = db.scalar(
            select(func.count(InviteAttempt.id)).where(
                and_(
                    InviteAttempt.workspace_id == workspace_id,
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
                    InviteAttempt.workspace_id == workspace_id,
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
                    workspace_id=workspace_id,
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
                    workspace_id=workspace_id,
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
                    workspace_id=workspace_id,
                    invite_run_id=run.id,
                    target_id=target_id,
                    candidate_id=cand.id,
                    status="failed",
                    error_code=code,
                    attempted_at=utcnow(),
                )
            )
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
                    workspace_id=workspace_id,
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


def run_invite(db: Session, tg_client: TelegramClient, target_id: int, policy: dict, workspace_id: int) -> InviteRun:
    run = InviteRun(
        workspace_id=workspace_id,
        status="running",
        target_id=target_id,
        policy=policy,
        started_at=utcnow(),
        stats={},
    )
    db.add(run)
    db.flush()
    return process_invite_run(db, tg_client, run)
