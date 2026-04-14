from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from time import monotonic
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    BroadcastDelivery,
    BroadcastRun,
    CandidateFeatures,
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
from app.telegram_accounts_service import mark_account_cooldown
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


def _normalize_stored_collect_mode(raw: str | None) -> str | None:
    if not raw:
        return None
    v = raw.strip().lower()
    if v in {"participants", "messages", "both", "auto"}:
        return v
    return None


def effective_collect_mode_for_source(src: Source) -> str:
    """Per-source `collect_mode` column, or `COLLECT_MODE` env if value missing/invalid."""
    explicit = _normalize_stored_collect_mode(getattr(src, "collect_mode", None))
    if explicit is not None:
        return explicit
    return _collect_mode()


def _aggregate_collect_mode_label(by: dict[str, dict[str, Any]]) -> str:
    modes = [row.get("collect_mode") for row in by.values() if isinstance(row.get("collect_mode"), str)]
    if not modes:
        return "participants"
    uniq = sorted(set(modes))
    return uniq[0] if len(uniq) == 1 else "mixed"


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


def _is_chat_admin_required_error(exc: Exception) -> bool:
    # Telethon error type is not imported in the API runtime.
    # We detect it by name to keep Telethon optional outside the worker.
    name = type(exc).__name__
    if name == "ChatAdminRequiredError":
        return True
    msg = str(exc)
    return "Chat admin privileges are required" in msg


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
    by_source_id: dict[str, dict[str, Any]] = {}

    def _flush_progress(*, force: bool = False) -> None:
        nonlocal last_commit_at
        if not force and (discovered_total - last_commit_at) < batch_size:
            return
        run.stats = {
            "discovered_total": discovered_total,
            "discovered_from_participants": discovered_from_participants,
            "discovered_from_messages": discovered_from_messages,
            "collect_mode": _aggregate_collect_mode_label(by_source_id),
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
        collect_mode = effective_collect_mode_for_source(src)
        by_source_id[sk] = {
            "collect_mode": collect_mode,
            "discovered": 0,
            "discovered_participants": 0,
            "discovered_messages": 0,
            "new_candidates": 0,
            "updated_candidates": 0,
            "new_source_links": 0,
            "errors": [],
        }

        seen: set[object] = set()
        participant_rows = 0

        if collect_mode in {"participants", "both", "auto"}:
            try:
                for u in tg_client.iter_participants(src.identifier):
                    participant_rows += 1
                    seen.add(_collect_user_dedupe_key(u))
                    _ingest_user(u, sk, sid, "participants")
            except Exception as e:
                if _is_chat_admin_required_error(e):
                    by_source_id[sk]["errors"].append(
                        {"code": "tg_admin_required", "message": "Chat admin privileges are required to list participants"}
                    )
                    # If we cannot read participants and this run is participants-only, fail gracefully.
                    if collect_mode == "participants":
                        run.status = "failed"
                        run.finished_at = utcnow()
                        run.stats = {
                            "error": {"code": "tg_admin_required", "message": "Admin rights required for participants list"},
                            "collect_mode": _aggregate_collect_mode_label(by_source_id),
                            "by_source_id": by_source_id,
                        }
                        db.flush()
                        return run
                    # For "auto"/"both" we can still continue with messages.
                    participant_rows = 0
                else:
                    raise

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
        "collect_mode": _aggregate_collect_mode_label(by_source_id),
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


def run_collect(
    db: Session,
    tg_client: TelegramClient,
    source_ids: list[int],
    workspace_id: int,
    *,
    telegram_account_id: int | None = None,
) -> CollectRun:
    run = CollectRun(
        workspace_id=workspace_id,
        status="running",
        source_ids=source_ids,
        telegram_account_id=telegram_account_id,
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


def _classify_invite_error(exc: BaseException) -> str:
    """Map Telethon/RPC errors to stable error_code strings."""
    if isinstance(exc, FloodWaitError):
        return "flood_wait"
    name = type(exc).__name__
    mapping = {
        "UserPrivacyRestrictedError": "privacy_restricted",
        "UserAlreadyParticipantError": "already_member",
        "UserNotMutualContactError": "not_mutual_contact",
        "UserDeletedError": "user_deleted",
        "UserBotError": "user_bot",
        "ChannelPrivateError": "channel_private",
        "ChatAdminRequiredError": "admin_required",
        "InviteHashExpiredError": "invite_expired",
    }
    if name in mapping:
        return mapping[name]
    return "unknown"


def _merge_failed_by_code(base: dict[str, int], code: str) -> None:
    base[code] = base.get(code, 0) + 1


def _compute_next_eligible_at_pacing(
    *,
    sent_in_min: int,
    sent_in_hour: int,
    max_per_minute: int,
    max_per_hour: int,
    window_min_start: float,
    window_hour_start: float,
) -> datetime:
    now_m = monotonic()
    wait_s = 0.0
    if sent_in_min >= max_per_minute:
        wait_s = max(wait_s, max(0.0, 60.0 - (now_m - window_min_start)))
    if sent_in_hour >= max_per_hour:
        wait_s = max(wait_s, max(0.0, 3600.0 - (now_m - window_hour_start)))
    return utcnow() + timedelta(seconds=int(max(1, wait_s)))


def _invite_run_stats_payload(
    *,
    attempted: int,
    success: int,
    skipped: int,
    failed: int,
    failed_by_code: dict[str, int],
    last_candidate_id: int | None = None,
    resume_after_candidate_id: int | None = None,
    pause_reason: str | None = None,
    next_eligible_at: datetime | None = None,
    remaining_candidates: int | None = None,
    flood_wait_seconds: int | None = None,
    stop_reason: str | None = None,
    max_invites_cap: int | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "attempted": attempted,
        "success": success,
        "skipped": skipped,
        "failed": failed,
        "failed_by_code": dict(failed_by_code),
    }
    if last_candidate_id is not None:
        out["last_candidate_id"] = last_candidate_id
    if resume_after_candidate_id is not None:
        out["resume_after_candidate_id"] = resume_after_candidate_id
    if pause_reason is not None:
        out["pause_reason"] = pause_reason
    if next_eligible_at is not None:
        out["next_eligible_at"] = next_eligible_at.isoformat()
    if remaining_candidates is not None:
        out["remaining_candidates"] = remaining_candidates
    if flood_wait_seconds is not None:
        out["flood_wait_seconds"] = flood_wait_seconds
    if stop_reason is not None:
        out["stop_reason"] = stop_reason
    if max_invites_cap is not None:
        out["max_invites_cap"] = max_invites_cap
    return out


def _invite_run_source_ids(run: InviteRun) -> list[int]:
    raw = getattr(run, "source_ids", None)
    if not isinstance(raw, list) or len(raw) == 0:
        return []
    out: list[int] = []
    for x in raw:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def process_invite_run(db: Session, tg_client: TelegramClient, run: InviteRun) -> InviteRun:
    workspace_id = run.workspace_id
    run.status = "running"
    if run.started_at is None:
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

    prev = dict(run.stats) if isinstance(run.stats, dict) else {}
    attempted = int(prev.get("attempted", 0))
    success = int(prev.get("success", 0))
    skipped = int(prev.get("skipped", 0))
    failed = int(prev.get("failed", 0))
    failed_by_code: dict[str, int] = {k: int(v) for k, v in (prev.get("failed_by_code") or {}).items() if isinstance(k, str)}

    resume_after = int(prev.get("resume_after_candidate_id") or 0)

    source_ids_filter = _invite_run_source_ids(run)
    linked_subq = None
    if source_ids_filter:
        linked_subq = (
            select(CandidateSourceLink.candidate_id)
            .where(
                CandidateSourceLink.workspace_id == workspace_id,
                CandidateSourceLink.source_id.in_(source_ids_filter),
            )
            .distinct()
        )

    max_per_minute = int(policy.get("max_per_minute", 2))
    max_per_hour = int(policy.get("max_per_hour", 30))
    max_invites: int | None = None
    raw_cap = policy.get("max_invites")
    if raw_cap is not None:
        try:
            mx = int(raw_cap)
            if 1 <= mx <= 100_000:
                max_invites = mx
        except (TypeError, ValueError):
            pass
    window_min_start = monotonic()
    window_hour_start = monotonic()
    sent_in_min = 0
    sent_in_hour = 0

    cand_stmt = (
        select(CandidateUser)
        .where(CandidateUser.workspace_id == workspace_id)
        .order_by(CandidateUser.id.asc())
    )
    if resume_after > 0:
        cand_stmt = cand_stmt.where(CandidateUser.id >= resume_after)
    if linked_subq is not None:
        cand_stmt = cand_stmt.where(CandidateUser.id.in_(linked_subq))

    count_q = select(func.count()).select_from(CandidateUser).where(CandidateUser.workspace_id == workspace_id)
    if resume_after > 0:
        count_q = count_q.where(CandidateUser.id >= resume_after)
    if linked_subq is not None:
        count_q = count_q.where(CandidateUser.id.in_(linked_subq))
    scan_total = int(db.scalar(count_q) or 0)

    candidates = db.scalars(cand_stmt).all()
    last_candidate_id: int | None = None
    if prev.get("last_candidate_id") is not None:
        try:
            last_candidate_id = int(prev["last_candidate_id"])
        except (TypeError, ValueError):
            last_candidate_id = None

    # Cap already reached in a previous segment (e.g. resume with nothing left to invite).
    if max_invites is not None and success >= max_invites:
        run.status = "succeeded"
        run.finished_at = utcnow()
        run.stats = _invite_run_stats_payload(
            attempted=attempted,
            success=success,
            skipped=skipped,
            failed=failed,
            failed_by_code=failed_by_code,
            last_candidate_id=last_candidate_id,
            remaining_candidates=scan_total,
            stop_reason="invite_cap_reached",
            max_invites_cap=max_invites,
        )
        db.flush()
        return run

    for idx, cand in enumerate(candidates):
        remaining_candidates = max(0, scan_total - idx)
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
        last_candidate_id = cand.id
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
                next_eligible_at = _compute_next_eligible_at_pacing(
                    sent_in_min=sent_in_min,
                    sent_in_hour=sent_in_hour,
                    max_per_minute=max_per_minute,
                    max_per_hour=max_per_hour,
                    window_min_start=window_min_start,
                    window_hour_start=window_hour_start,
                )
                run.status = "paused"
                run.stats = _invite_run_stats_payload(
                    attempted=attempted,
                    success=success,
                    skipped=skipped,
                    failed=failed,
                    failed_by_code=failed_by_code,
                    last_candidate_id=last_candidate_id,
                    resume_after_candidate_id=cand.id,
                    pause_reason="pacing_limit",
                    next_eligible_at=next_eligible_at,
                    remaining_candidates=remaining_candidates,
                )
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
            if max_invites is not None and success >= max_invites:
                run.status = "succeeded"
                run.finished_at = utcnow()
                run.stats = _invite_run_stats_payload(
                    attempted=attempted,
                    success=success,
                    skipped=skipped,
                    failed=failed,
                    failed_by_code=failed_by_code,
                    last_candidate_id=last_candidate_id,
                    remaining_candidates=remaining_candidates,
                    stop_reason="invite_cap_reached",
                    max_invites_cap=max_invites,
                )
                db.flush()
                return run
        except FloodWaitError as e:
            failed += 1
            code = "flood_wait"
            _merge_failed_by_code(failed_by_code, code)
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
            fw = int(getattr(e, "seconds", 0) or 0)
            next_eligible_at = utcnow() + timedelta(seconds=max(1, fw))
            run.status = "paused"
            run.stats = _invite_run_stats_payload(
                attempted=attempted,
                success=success,
                skipped=skipped,
                failed=failed,
                failed_by_code=failed_by_code,
                last_candidate_id=last_candidate_id,
                resume_after_candidate_id=cand.id,
                pause_reason="flood_wait",
                next_eligible_at=next_eligible_at,
                remaining_candidates=remaining_candidates,
                flood_wait_seconds=fw,
            )
            db.flush()
            return run
        except Exception as e:
            failed += 1
            code = _classify_invite_error(e)
            _merge_failed_by_code(failed_by_code, code)
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
    run.stats = _invite_run_stats_payload(
        attempted=attempted,
        success=success,
        skipped=skipped,
        failed=failed,
        failed_by_code=failed_by_code,
        last_candidate_id=last_candidate_id,
        remaining_candidates=0,
    )
    return run


def run_invite(
    db: Session,
    tg_client: TelegramClient,
    target_id: int,
    policy: dict,
    workspace_id: int,
    *,
    source_ids: list[int] | None = None,
    telegram_account_id: int | None = None,
) -> InviteRun:
    ids = list(source_ids) if source_ids is not None else []
    run = InviteRun(
        workspace_id=workspace_id,
        status="running",
        target_id=target_id,
        telegram_account_id=telegram_account_id,
        source_ids=ids,
        policy=policy,
        started_at=utcnow(),
        stats={},
    )
    db.add(run)
    db.flush()
    return process_invite_run(db, tg_client, run)


def _broadcast_run_source_ids(run: BroadcastRun) -> list[int]:
    raw = getattr(run, "source_ids", None)
    if not isinstance(raw, list) or len(raw) == 0:
        return []
    out: list[int] = []
    for x in raw:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def _broadcast_run_candidate_ids(run: BroadcastRun) -> list[int]:
    raw = getattr(run, "candidate_ids", None)
    if not isinstance(raw, list) or len(raw) == 0:
        return []
    out: list[int] = []
    for x in raw:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return sorted(set(out))


def _broadcast_candidate_stmt(
    *,
    workspace_id: int,
    source_ids: list[int],
    candidate_ids: list[int],
    resume_after: int,
):
    linked_subq = None
    if source_ids:
        linked_subq = (
            select(CandidateSourceLink.candidate_id)
            .where(
                CandidateSourceLink.workspace_id == workspace_id,
                CandidateSourceLink.source_id.in_(source_ids),
            )
            .distinct()
        )

    cand_stmt = select(CandidateUser).where(CandidateUser.workspace_id == workspace_id).order_by(CandidateUser.id.asc())
    if resume_after > 0:
        cand_stmt = cand_stmt.where(CandidateUser.id >= resume_after)

    if candidate_ids and source_ids:
        cand_stmt = cand_stmt.where(
            CandidateUser.id.in_(candidate_ids),
            CandidateUser.id.in_(linked_subq),
        )
    elif candidate_ids:
        cand_stmt = cand_stmt.where(CandidateUser.id.in_(candidate_ids))
    elif source_ids:
        cand_stmt = cand_stmt.where(CandidateUser.id.in_(linked_subq))

    return cand_stmt


def _broadcast_run_stats_payload(
    *,
    attempted: int,
    success: int,
    skipped: int,
    skipped_duplicate: int,
    failed: int,
    failed_by_code: dict[str, int],
    last_candidate_id: int | None = None,
    resume_after_candidate_id: int | None = None,
    pause_reason: str | None = None,
    next_eligible_at: datetime | None = None,
    remaining_candidates: int | None = None,
    flood_wait_seconds: int | None = None,
    stop_reason: str | None = None,
    max_total_cap: int | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "attempted": attempted,
        "success": success,
        "skipped": skipped,
        "skipped_duplicate": skipped_duplicate,
        "failed": failed,
        "failed_by_code": dict(failed_by_code),
    }
    if last_candidate_id is not None:
        out["last_candidate_id"] = last_candidate_id
    if resume_after_candidate_id is not None:
        out["resume_after_candidate_id"] = resume_after_candidate_id
    if pause_reason is not None:
        out["pause_reason"] = pause_reason
    if next_eligible_at is not None:
        out["next_eligible_at"] = next_eligible_at.isoformat()
    if remaining_candidates is not None:
        out["remaining_candidates"] = remaining_candidates
    if flood_wait_seconds is not None:
        out["flood_wait_seconds"] = flood_wait_seconds
    if stop_reason is not None:
        out["stop_reason"] = stop_reason
    if max_total_cap is not None:
        out["max_total_cap"] = max_total_cap
    return out


def _broadcast_already_sent(db: Session, workspace_id: int, message_key: str, tg_user_id: int) -> bool:
    n = db.scalar(
        select(func.count(BroadcastDelivery.id)).where(
            BroadcastDelivery.workspace_id == workspace_id,
            BroadcastDelivery.message_key == message_key,
            BroadcastDelivery.tg_user_id == tg_user_id,
            BroadcastDelivery.status == "success",
        )
    )
    return bool(n and n > 0)


def _broadcast_dm_recipient_mode(policy: dict) -> str:
    raw = policy.get("dm_recipient") if isinstance(policy, dict) else None
    if raw == "username":
        return "username"
    return "tg_user_id"


def _broadcast_already_sent_for_candidate(db: Session, workspace_id: int, message_key: str, candidate_id: int) -> bool:
    n = db.scalar(
        select(func.count(BroadcastDelivery.id)).where(
            BroadcastDelivery.workspace_id == workspace_id,
            BroadcastDelivery.message_key == message_key,
            BroadcastDelivery.candidate_id == candidate_id,
            BroadcastDelivery.status == "success",
        )
    )
    return bool(n and n > 0)


def _broadcast_duplicate_for_message_key(db: Session, workspace_id: int, message_key: str, cand: CandidateUser) -> bool:
    if cand.tg_user_id is not None:
        return _broadcast_already_sent(db, workspace_id, message_key, int(cand.tg_user_id))
    return _broadcast_already_sent_for_candidate(db, workspace_id, message_key, cand.id)


def _broadcast_row_tg_user_id(cand: CandidateUser) -> int:
    """Fallback numeric id for delivery rows when candidate has no tg_user_id (skipped / edge cases)."""
    return int(cand.tg_user_id) if cand.tg_user_id is not None else 0


def _classify_dm_error(exc: BaseException) -> str:
    if isinstance(exc, FloodWaitError):
        return "flood_wait"
    name = type(exc).__name__
    mapping = {
        "UserPrivacyRestrictedError": "privacy_restricted",
        "UserIsBlockedError": "user_blocked",
        "InputUserDeactivatedError": "user_deactivated",
        "PeerIdInvalidError": "peer_invalid",
        "UserBotError": "user_bot",
        "ChatWriteForbiddenError": "write_forbidden",
        # Account-level spam / stranger DM limits (Telethon PeerFloodError, RPC PEER_FLOOD).
        "PeerFloodError": "peer_flood",
        "UserNotMutualContactError": "not_mutual_contact",
        # Premium / paid DM gates (names from telethon.errors.rpcerrorlist, may vary by layer).
        "PremiumAccountRequiredError": "premium_required",
        "PrivacyPremiumRequiredError": "privacy_premium_required",
        "PaymentRequiredError": "payment_required",
    }
    if name in mapping:
        return mapping[name]
    return _classify_invite_error(exc)


def _maybe_suppress_after_dm_failure(
    db: Session, workspace_id: int, candidate: CandidateUser, error_code: str
) -> None:
    if error_code not in {"user_blocked", "user_deactivated"}:
        return
    if is_suppressed(db, workspace_id, candidate, utcnow()):
        return
    db.add(
        SuppressionList(
            workspace_id=workspace_id,
            tg_user_id=candidate.tg_user_id,
            username=normalize_username(candidate.username),
            reason=f"dm_{error_code}",
            until=None,
        )
    )
    db.flush()


def count_broadcast_preview(
    db: Session,
    workspace_id: int,
    *,
    message_key: str,
    source_ids: list[int],
    candidate_ids: list[int],
    dm_recipient: str = "tg_user_id",
) -> dict[str, int]:
    """Dry-run counts without creating a run (no Telegram calls)."""
    sids = sorted(set(source_ids))
    cids = sorted(set(candidate_ids))
    mode = "username" if dm_recipient == "username" else "tg_user_id"
    stmt = _broadcast_candidate_stmt(
        workspace_id=workspace_id,
        source_ids=sids,
        candidate_ids=cids,
        resume_after=0,
    )
    candidates = db.scalars(stmt).all()
    now = utcnow()
    scan_total = len(candidates)
    suppressed_n = 0
    missing_id_n = 0
    missing_username_n = 0
    already_sent_n = 0
    eligible_n = 0
    for cand in candidates:
        if is_suppressed(db, workspace_id, cand, now):
            suppressed_n += 1
            continue
        if mode == "tg_user_id":
            if cand.tg_user_id is None:
                missing_id_n += 1
                continue
        else:
            if normalize_username(cand.username) is None:
                missing_username_n += 1
                continue
        if _broadcast_duplicate_for_message_key(db, workspace_id, message_key, cand):
            already_sent_n += 1
            continue
        eligible_n += 1
    return {
        "scan_total": scan_total,
        "suppressed": suppressed_n,
        "missing_tg_user_id": missing_id_n,
        "missing_username": missing_username_n,
        "already_sent": already_sent_n,
        "eligible": eligible_n,
    }


def process_broadcast_run(
    db: Session,
    tg_client: TelegramClient,
    run: BroadcastRun,
    *,
    telegram_account_id: int | None = None,
) -> BroadcastRun:
    workspace_id = run.workspace_id
    message_key = (run.message_key or "").strip()
    if not message_key:
        raise ValueError("message_key_required")

    run.status = "running"
    if run.started_at is None:
        run.started_at = utcnow()
    run.finished_at = None
    if not isinstance(run.stats, dict):
        run.stats = {}
    db.flush()

    logger.info(
        "broadcast_run processing run_id=%s workspace_id=%s message_key=%s",
        run.id,
        workspace_id,
        message_key,
    )

    policy = run.policy if isinstance(run.policy, dict) else {}
    max_per_minute = int(policy.get("max_per_minute", 2))
    max_per_hour = int(policy.get("max_per_hour", 30))
    verify_outbox_after_send = bool(policy.get("verify_outbox_after_send"))
    dm_mode = _broadcast_dm_recipient_mode(policy)
    targeting_segment = policy.get("targeting_segment") if isinstance(policy, dict) else None
    min_send_score_raw = policy.get("min_send_score") if isinstance(policy, dict) else None
    min_send_score: int | None = None
    if min_send_score_raw is not None:
        try:
            min_send_score = int(min_send_score_raw)
        except (TypeError, ValueError):
            min_send_score = None
    max_total: int | None = None
    raw_cap = policy.get("max_total")
    if raw_cap is not None:
        try:
            mx = int(raw_cap)
            if 1 <= mx <= 100_000:
                max_total = mx
        except (TypeError, ValueError):
            pass

    prev = dict(run.stats) if isinstance(run.stats, dict) else {}
    attempted = int(prev.get("attempted", 0))
    success = int(prev.get("success", 0))
    skipped = int(prev.get("skipped", 0))
    skipped_duplicate = int(prev.get("skipped_duplicate", 0))
    failed = int(prev.get("failed", 0))
    failed_by_code: dict[str, int] = {
        k: int(v) for k, v in (prev.get("failed_by_code") or {}).items() if isinstance(k, str)
    }

    resume_after = int(prev.get("resume_after_candidate_id") or 0)
    source_ids_filter = _broadcast_run_source_ids(run)
    candidate_ids_filter = _broadcast_run_candidate_ids(run)

    cand_stmt = _broadcast_candidate_stmt(
        workspace_id=workspace_id,
        source_ids=source_ids_filter,
        candidate_ids=candidate_ids_filter,
        resume_after=resume_after,
    )
    if targeting_segment in {"A", "B", "C"} or min_send_score is not None:
        feat_q = select(CandidateFeatures.candidate_id).where(CandidateFeatures.workspace_id == workspace_id)
        if targeting_segment in {"A", "B", "C"}:
            feat_q = feat_q.where(CandidateFeatures.segment == str(targeting_segment))
        if min_send_score is not None:
            feat_q = feat_q.where(CandidateFeatures.send_score >= int(min_send_score))
        cand_stmt = cand_stmt.where(CandidateUser.id.in_(feat_q))

    count_base = select(func.count()).select_from(CandidateUser).where(CandidateUser.workspace_id == workspace_id)
    if resume_after > 0:
        count_base = count_base.where(CandidateUser.id >= resume_after)
    if candidate_ids_filter and source_ids_filter:
        count_base = count_base.where(
            CandidateUser.id.in_(candidate_ids_filter),
            CandidateUser.id.in_(
                select(CandidateSourceLink.candidate_id)
                .where(
                    CandidateSourceLink.workspace_id == workspace_id,
                    CandidateSourceLink.source_id.in_(source_ids_filter),
                )
                .distinct()
            ),
        )
    elif candidate_ids_filter:
        count_base = count_base.where(CandidateUser.id.in_(candidate_ids_filter))
    elif source_ids_filter:
        count_base = count_base.where(
            CandidateUser.id.in_(
                select(CandidateSourceLink.candidate_id)
                .where(
                    CandidateSourceLink.workspace_id == workspace_id,
                    CandidateSourceLink.source_id.in_(source_ids_filter),
                )
                .distinct()
            )
        )
    scan_total = int(db.scalar(count_base) or 0)

    candidates = db.scalars(cand_stmt).all()
    last_candidate_id: int | None = None
    if prev.get("last_candidate_id") is not None:
        try:
            last_candidate_id = int(prev["last_candidate_id"])
        except (TypeError, ValueError):
            last_candidate_id = None

    window_min_start = monotonic()
    window_hour_start = monotonic()
    # Pacing: max_per_minute / max_per_hour count Telegram send attempts (any outcome), not only successes.
    attempts_in_min = 0
    attempts_in_hour = 0

    now = utcnow()
    body = run.message_body if isinstance(run.message_body, str) else ""

    if max_total is not None and success >= max_total:
        run.status = "succeeded"
        run.finished_at = utcnow()
        run.stats = _broadcast_run_stats_payload(
            attempted=attempted,
            success=success,
            skipped=skipped,
            skipped_duplicate=skipped_duplicate,
            failed=failed,
            failed_by_code=failed_by_code,
            last_candidate_id=last_candidate_id,
            remaining_candidates=scan_total,
            stop_reason="max_total_reached",
            max_total_cap=max_total,
        )
        db.flush()
        return run

    acc_id = telegram_account_id
    if acc_id is None:
        acc_id = getattr(run, "telegram_account_id", None)

    for idx, cand in enumerate(candidates):
        remaining_candidates = max(0, scan_total - idx)
        if is_suppressed(db, workspace_id, cand, now):
            continue

        last_candidate_id = cand.id

        if dm_mode == "tg_user_id":
            if cand.tg_user_id is None:
                skipped += 1
                continue
        elif normalize_username(cand.username) is None:
            skipped += 1
            continue

        row_tgid = _broadcast_row_tg_user_id(cand)
        if _broadcast_duplicate_for_message_key(db, workspace_id, message_key, cand):
            skipped_duplicate += 1
            db.add(
                BroadcastDelivery(
                    workspace_id=workspace_id,
                    broadcast_run_id=run.id,
                    message_key=message_key,
                    candidate_id=cand.id,
                    tg_user_id=row_tgid,
                    status="skipped",
                    error_code="already_sent",
                    attempted_at=utcnow(),
                )
            )
            continue

        uname = normalize_username(cand.username) if dm_mode == "username" else None
        db_tgid = row_tgid

        try:
            now_m = monotonic()
            if now_m - window_min_start >= 60:
                window_min_start = now_m
                attempts_in_min = 0
            if now_m - window_hour_start >= 3600:
                window_hour_start = now_m
                attempts_in_hour = 0
            if attempts_in_min >= max_per_minute or attempts_in_hour >= max_per_hour:
                next_eligible_at = _compute_next_eligible_at_pacing(
                    sent_in_min=attempts_in_min,
                    sent_in_hour=attempts_in_hour,
                    max_per_minute=max_per_minute,
                    max_per_hour=max_per_hour,
                    window_min_start=window_min_start,
                    window_hour_start=window_hour_start,
                )
                run.status = "paused"
                run.stats = _broadcast_run_stats_payload(
                    attempted=attempted,
                    success=success,
                    skipped=skipped,
                    skipped_duplicate=skipped_duplicate,
                    failed=failed,
                    failed_by_code=failed_by_code,
                    last_candidate_id=last_candidate_id,
                    resume_after_candidate_id=cand.id,
                    pause_reason="pacing_limit",
                    next_eligible_at=next_eligible_at,
                    remaining_candidates=remaining_candidates,
                )
                db.flush()
                return run

            attempted += 1
            if dm_mode == "username":
                assert uname is not None
                send_result = tg_client.send_direct_message(body, username=uname)
            else:
                send_result = tg_client.send_direct_message(body, tg_user_id=int(cand.tg_user_id))
            attempts_in_min += 1
            attempts_in_hour += 1

            tgid: int | None
            if cand.tg_user_id is not None:
                tgid = int(cand.tg_user_id)
            else:
                tgid = send_result.resolved_tg_user_id
            if tgid is None:
                failed += 1
                _merge_failed_by_code(failed_by_code, "missing_resolved_tg_user_id")
                db.add(
                    BroadcastDelivery(
                        workspace_id=workspace_id,
                        broadcast_run_id=run.id,
                        message_key=message_key,
                        candidate_id=cand.id,
                        tg_user_id=0,
                        status="failed",
                        error_code="missing_resolved_tg_user_id",
                        attempted_at=utcnow(),
                    )
                )
                continue
            tgid = int(tgid)
            db_tgid = tgid

            tg_mid = send_result.message_id
            if verify_outbox_after_send and tg_client.supports_outbox_verify():
                if tg_mid is None:
                    failed += 1
                    _merge_failed_by_code(failed_by_code, "no_telegram_message_id")
                    db.add(
                        BroadcastDelivery(
                            workspace_id=workspace_id,
                            broadcast_run_id=run.id,
                            message_key=message_key,
                            candidate_id=cand.id,
                            tg_user_id=tgid,
                            status="failed",
                            error_code="no_telegram_message_id",
                            attempted_at=utcnow(),
                            telegram_message_id=None,
                        )
                    )
                    continue
                try:
                    in_outbox = tg_client.verify_direct_message_outbox(int(tg_mid), tg_user_id=tgid)
                except FloodWaitError as e:
                    attempts_in_min += 1
                    attempts_in_hour += 1
                    failed += 1
                    code = "flood_wait"
                    _merge_failed_by_code(failed_by_code, code)
                    db.add(
                        BroadcastDelivery(
                            workspace_id=workspace_id,
                            broadcast_run_id=run.id,
                            message_key=message_key,
                            candidate_id=cand.id,
                            tg_user_id=tgid,
                            status="failed",
                            error_code=code,
                            attempted_at=utcnow(),
                            telegram_message_id=int(tg_mid),
                        )
                    )
                    fw = int(getattr(e, "seconds", 0) or 0)
                    next_eligible_at = utcnow() + timedelta(seconds=max(1, fw))
                    mark_account_cooldown(db, acc_id, next_eligible_at)
                    run.status = "paused"
                    run.stats = _broadcast_run_stats_payload(
                        attempted=attempted,
                        success=success,
                        skipped=skipped,
                        skipped_duplicate=skipped_duplicate,
                        failed=failed,
                        failed_by_code=failed_by_code,
                        last_candidate_id=last_candidate_id,
                        resume_after_candidate_id=cand.id,
                        pause_reason="flood_wait",
                        next_eligible_at=next_eligible_at,
                        remaining_candidates=remaining_candidates,
                        flood_wait_seconds=fw,
                    )
                    db.flush()
                    return run
                except Exception as e:
                    failed += 1
                    code = _classify_dm_error(e)
                    _merge_failed_by_code(failed_by_code, code)
                    db.add(
                        BroadcastDelivery(
                            workspace_id=workspace_id,
                            broadcast_run_id=run.id,
                            message_key=message_key,
                            candidate_id=cand.id,
                            tg_user_id=tgid,
                            status="failed",
                            error_code=code,
                            attempted_at=utcnow(),
                            telegram_message_id=int(tg_mid),
                        )
                    )
                    _maybe_suppress_after_dm_failure(db, workspace_id, cand, code)
                    continue
                if not in_outbox:
                    failed += 1
                    _merge_failed_by_code(failed_by_code, "outbox_verify_failed")
                    db.add(
                        BroadcastDelivery(
                            workspace_id=workspace_id,
                            broadcast_run_id=run.id,
                            message_key=message_key,
                            candidate_id=cand.id,
                            tg_user_id=tgid,
                            status="failed",
                            error_code="outbox_verify_failed",
                            attempted_at=utcnow(),
                            telegram_message_id=int(tg_mid),
                        )
                    )
                    continue

            try:
                with db.begin_nested():
                    db.add(
                        BroadcastDelivery(
                            workspace_id=workspace_id,
                            broadcast_run_id=run.id,
                            message_key=message_key,
                            candidate_id=cand.id,
                            tg_user_id=tgid,
                            status="success",
                            error_code=None,
                            attempted_at=utcnow(),
                            telegram_message_id=int(tg_mid) if tg_mid is not None else None,
                        )
                    )
                    db.flush()
            except IntegrityError:
                skipped_duplicate += 1
            else:
                success += 1
        except FloodWaitError as e:
            attempts_in_min += 1
            attempts_in_hour += 1
            failed += 1
            code = "flood_wait"
            _merge_failed_by_code(failed_by_code, code)
            db.add(
                BroadcastDelivery(
                    workspace_id=workspace_id,
                    broadcast_run_id=run.id,
                    message_key=message_key,
                    candidate_id=cand.id,
                    tg_user_id=db_tgid,
                    status="failed",
                    error_code=code,
                    attempted_at=utcnow(),
                )
            )
            fw = int(getattr(e, "seconds", 0) or 0)
            next_eligible_at = utcnow() + timedelta(seconds=max(1, fw))
            mark_account_cooldown(db, acc_id, next_eligible_at)
            run.status = "paused"
            run.stats = _broadcast_run_stats_payload(
                attempted=attempted,
                success=success,
                skipped=skipped,
                skipped_duplicate=skipped_duplicate,
                failed=failed,
                failed_by_code=failed_by_code,
                last_candidate_id=last_candidate_id,
                resume_after_candidate_id=cand.id,
                pause_reason="flood_wait",
                next_eligible_at=next_eligible_at,
                remaining_candidates=remaining_candidates,
                flood_wait_seconds=fw,
            )
            db.flush()
            return run
        except Exception as e:
            attempts_in_min += 1
            attempts_in_hour += 1
            failed += 1
            code = _classify_dm_error(e)
            _merge_failed_by_code(failed_by_code, code)
            db.add(
                BroadcastDelivery(
                    workspace_id=workspace_id,
                    broadcast_run_id=run.id,
                    message_key=message_key,
                    candidate_id=cand.id,
                    tg_user_id=db_tgid,
                    status="failed",
                    error_code=code,
                    attempted_at=utcnow(),
                )
            )
            _maybe_suppress_after_dm_failure(db, workspace_id, cand, code)

        # Guardrail: if block/privacy failures accumulate early, pause to reduce ban risk.
        # This is intentionally conservative and uses aggregate counters (no per-window state).
        if attempted >= 20:
            n_block = int(failed_by_code.get("user_blocked", 0) or 0)
            n_priv = int(failed_by_code.get("privacy_restricted", 0) or 0)
            n_peer_flood = int(failed_by_code.get("peer_flood", 0) or 0)
            if n_peer_flood > 0 or (n_block + n_priv) >= 5:
                run.status = "paused"
                run.stats = _broadcast_run_stats_payload(
                    attempted=attempted,
                    success=success,
                    skipped=skipped,
                    skipped_duplicate=skipped_duplicate,
                    failed=failed,
                    failed_by_code=failed_by_code,
                    last_candidate_id=last_candidate_id,
                    resume_after_candidate_id=cand.id,
                    pause_reason="risk_guardrail",
                    next_eligible_at=(utcnow() + timedelta(minutes=30)),
                    remaining_candidates=remaining_candidates,
                )
                db.flush()
                return run

        if max_total is not None and success >= max_total:
            run.status = "succeeded"
            run.finished_at = utcnow()
            run.stats = _broadcast_run_stats_payload(
                attempted=attempted,
                success=success,
                skipped=skipped,
                skipped_duplicate=skipped_duplicate,
                failed=failed,
                failed_by_code=failed_by_code,
                last_candidate_id=last_candidate_id,
                remaining_candidates=remaining_candidates,
                stop_reason="max_total_reached",
                max_total_cap=max_total,
            )
            db.flush()
            return run

    run.status = "succeeded"
    run.finished_at = utcnow()
    run.stats = _broadcast_run_stats_payload(
        attempted=attempted,
        success=success,
        skipped=skipped,
        skipped_duplicate=skipped_duplicate,
        failed=failed,
        failed_by_code=failed_by_code,
        last_candidate_id=last_candidate_id,
        remaining_candidates=0,
    )
    return run


def run_broadcast(
    db: Session,
    tg_client: TelegramClient,
    workspace_id: int,
    *,
    message_key: str,
    message_body: str,
    source_ids: list[int] | None = None,
    candidate_ids: list[int] | None = None,
    policy: dict,
    telegram_account_id: int | None = None,
) -> BroadcastRun:
    run = BroadcastRun(
        workspace_id=workspace_id,
        status="running",
        message_key=(message_key or "").strip(),
        message_body=message_body,
        source_ids=list(source_ids) if source_ids is not None else [],
        candidate_ids=list(candidate_ids) if candidate_ids is not None else [],
        policy=policy,
        telegram_account_id=telegram_account_id,
        started_at=utcnow(),
        stats={},
    )
    db.add(run)
    db.flush()
    return process_broadcast_run(db, tg_client, run, telegram_account_id=telegram_account_id)
