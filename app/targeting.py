from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CandidateFeatures, CandidateSourceLink, CandidateUser, Source, utcnow
from app.services import effective_collect_mode_for_source, normalize_username
from app.telegram_client import TelegramClient, TgMessageSnippet


_WORD_RE = re.compile(r"[\\w\\-]{3,}", re.UNICODE)


@dataclass(frozen=True)
class TargetingParams:
    # Limits to keep Telegram usage low and deterministic.
    min_message_date: datetime | None = None
    max_messages_per_source: int = 200
    max_keywords: int = 20


def _intent_flags_from_text(text: str) -> set[str]:
    t = text.lower()
    flags: set[str] = set()
    for key, flag in [
        ("ищу", "seek"),
        ("нуж", "need"),
        ("порекоменду", "recommend"),
        ("куплю", "buy"),
        ("продам", "sell"),
        ("вопрос", "question"),
        ("как ", "howto"),
    ]:
        if key in t:
            flags.add(flag)
    return flags


def _keywords_from_text(text: str) -> list[str]:
    words = [w.lower() for w in _WORD_RE.findall(text)]
    # Keep a very small, safe set of tokens (no PII handling here; just ranking).
    out: list[str] = []
    seen: set[str] = set()
    for w in words:
        if len(w) < 3 or len(w) > 32:
            continue
        if w.isdigit():
            continue
        if w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= 50:
            break
    return out


def _score_and_segment(
    *,
    seen_as: str,
    last_seen_at: datetime,
    source_count: int,
    source_priority_score: int,
    has_username: bool,
    intent_flags: set[str],
    now: datetime,
) -> tuple[int, int, int, str, dict]:
    reasons: dict[str, object] = {}
    warmth = 0
    risk = 0

    if seen_as in {"messages", "both"}:
        warmth += 30
        reasons["seen_as"] = seen_as
    elif seen_as in {"participants"}:
        risk += 30
        reasons["seen_as"] = seen_as
    else:
        # mixed/unknown
        risk += 10
        reasons["seen_as"] = seen_as

    # Freshness: last 7 days is much safer.
    age_days = max(0, int((now - last_seen_at).total_seconds() // 86400))
    reasons["age_days"] = age_days
    if age_days <= 3:
        warmth += 20
    elif age_days <= 7:
        warmth += 10
    elif age_days >= 30:
        risk += 10

    warmth += min(20, max(0, source_count) * 2)
    reasons["source_count"] = int(source_count)

    warmth += min(20, max(0, source_priority_score))
    reasons["source_priority_score"] = int(source_priority_score)

    if not has_username:
        # Affects DM-by-username and is correlated with lower profile completeness.
        risk += 5
        reasons["no_username"] = True

    if intent_flags:
        warmth += 10
        reasons["intent_flags"] = sorted(intent_flags)

    send = warmth - risk
    if send >= 40 and seen_as in {"messages", "both"} and age_days <= 7:
        segment = "A"
    elif send >= 10 and seen_as in {"messages", "both"}:
        segment = "B"
    else:
        segment = "C"
    return warmth, risk, send, segment, reasons


def recompute_candidate_features(
    db: Session,
    tg: TelegramClient,
    *,
    workspace_id: int,
    source_ids: list[int] | None = None,
    params: TargetingParams | None = None,
) -> int:
    """Compute/refresh candidate targeting features for a workspace.

    Returns number of upserted rows.
    """
    p = params or TargetingParams()
    now = utcnow()

    src_stmt = select(Source).where(Source.workspace_id == workspace_id, Source.enabled.is_(True))
    if source_ids:
        src_stmt = src_stmt.where(Source.id.in_([int(x) for x in source_ids]))
    sources = db.scalars(src_stmt).all()

    # Aggregate per candidate: seen_as, source_count, source_priority_score, keywords, intent flags.
    agg: dict[int, dict[str, object]] = {}

    def _get_row(cid: int) -> dict[str, object]:
        if cid not in agg:
            agg[cid] = {
                "seen_participants": False,
                "seen_messages": False,
                "source_ids": set(),
                "source_priority_score": 0,
                "keywords": set(),
                "intent": set(),
            }
        return agg[cid]

    # Source priority: simple heuristic — smaller sources are usually more niche (optional), plus manual override via notes.
    # For now: +1 per source by default. (Can evolve later.)
    for src in sources:
        src_ident = (src.identifier or "").strip()
        collect_mode = effective_collect_mode_for_source(src)
        priority = 1
        row_priority = int(priority)

        # Participants signal (very weak).
        if collect_mode in {"participants", "both", "auto"}:
            for u in tg.iter_participants(src_ident):
                if u.tg_user_id is None and normalize_username(u.username) is None:
                    continue
                cand = db.scalar(
                    select(CandidateUser).where(
                        CandidateUser.workspace_id == workspace_id,
                        (CandidateUser.tg_user_id == u.tg_user_id) if u.tg_user_id is not None else False,
                    )
                )
                # Fall back to username match if needed.
                if cand is None:
                    un = normalize_username(u.username)
                    if un is not None:
                        cand = db.scalar(
                            select(CandidateUser).where(CandidateUser.workspace_id == workspace_id, CandidateUser.username == un)
                        )
                if cand is None:
                    continue
                r = _get_row(int(cand.id))
                r["seen_participants"] = True
                (r["source_ids"]).add(int(src.id))  # type: ignore[union-attr]
                r["source_priority_score"] = int(r.get("source_priority_score", 0) or 0) + row_priority

        # Messages signals (stronger).
        if collect_mode in {"messages", "both"} or (collect_mode == "auto"):
            min_date = p.min_message_date
            if min_date is None:
                # Default: last 14 days.
                min_date = (now - timedelta(days=14)).replace(tzinfo=timezone.utc)
            for snip in tg.iter_message_snippets(src_ident, limit=p.max_messages_per_source, min_date=min_date):
                _apply_snippet(db, workspace_id, src.id, snip, _get_row, row_priority, p)

    # Also add pure source context from links (candidates that exist but may not be in tg iteration now).
    link_rows = db.execute(
        select(CandidateSourceLink.candidate_id, func.count(CandidateSourceLink.source_id))
        .where(CandidateSourceLink.workspace_id == workspace_id)
        .group_by(CandidateSourceLink.candidate_id)
    ).all()
    for cid, cnt in link_rows:
        r = _get_row(int(cid))
        # only fill if empty
        if not r.get("source_ids"):
            r["source_count_hint"] = int(cnt)

    # Upsert features rows.
    upserted = 0
    for cid, r in agg.items():
        cand = db.get(CandidateUser, cid)
        if cand is None or cand.workspace_id != workspace_id:
            continue
        seen_participants = bool(r.get("seen_participants"))
        seen_messages = bool(r.get("seen_messages"))
        if seen_participants and seen_messages:
            seen_as = "both"
        elif seen_messages:
            seen_as = "messages"
        elif seen_participants:
            seen_as = "participants"
        else:
            seen_as = "mixed"

        source_ids_set: set[int] = r.get("source_ids") if isinstance(r.get("source_ids"), set) else set()
        source_count = len(source_ids_set) or int(r.get("source_count_hint", 0) or 0)
        priority_score = int(r.get("source_priority_score", 0) or 0)

        kw_set: set[str] = r.get("keywords") if isinstance(r.get("keywords"), set) else set()
        intent_set: set[str] = r.get("intent") if isinstance(r.get("intent"), set) else set()
        topic_keywords = sorted(list(kw_set))[: p.max_keywords]
        intent_flags = sorted(list(intent_set))[: 20]

        has_username = normalize_username(cand.username) is not None
        has_display = bool((cand.display_name or "").strip())

        warmth, risk, send, segment, reasons = _score_and_segment(
            seen_as=seen_as,
            last_seen_at=cand.last_seen_at if cand.last_seen_at.tzinfo else cand.last_seen_at.replace(tzinfo=timezone.utc),
            source_count=source_count,
            source_priority_score=priority_score,
            has_username=has_username,
            intent_flags=set(intent_flags),
            now=now,
        )

        reasons.update(
            {
                "topic_keywords": topic_keywords[:10],
                "has_username": has_username,
            }
        )

        existing = db.scalar(
            select(CandidateFeatures).where(
                CandidateFeatures.workspace_id == workspace_id,
                CandidateFeatures.candidate_id == cid,
            )
        )
        if existing is None:
            existing = CandidateFeatures(workspace_id=workspace_id, candidate_id=cid)
            db.add(existing)

        existing.computed_at = now
        existing.source_count = int(source_count)
        existing.source_priority_score = int(priority_score)
        existing.seen_as = seen_as
        existing.has_username = bool(has_username)
        existing.has_display_name = bool(has_display)
        existing.topic_keywords = list(topic_keywords)
        existing.intent_flags = list(intent_flags)
        existing.warmth_score = int(warmth)
        existing.risk_score = int(risk)
        existing.send_score = int(send)
        existing.segment = str(segment)
        existing.reasons = dict(reasons)
        upserted += 1

    db.flush()
    return upserted


def _apply_snippet(
    db: Session,
    workspace_id: int,
    src_id: int,
    snip: TgMessageSnippet,
    get_row,
    row_priority: int,
    p: TargetingParams,
) -> None:
    sender = snip.sender
    if sender.tg_user_id is None and normalize_username(sender.username) is None:
        return
    cand = None
    if sender.tg_user_id is not None:
        cand = db.scalar(
            select(CandidateUser).where(CandidateUser.workspace_id == workspace_id, CandidateUser.tg_user_id == int(sender.tg_user_id))
        )
    if cand is None:
        un = normalize_username(sender.username)
        if un is not None:
            cand = db.scalar(select(CandidateUser).where(CandidateUser.workspace_id == workspace_id, CandidateUser.username == un))
    if cand is None:
        return
    r = get_row(int(cand.id))
    r["seen_messages"] = True
    (r["source_ids"]).add(int(src_id))  # type: ignore[union-attr]
    r["source_priority_score"] = int(r.get("source_priority_score", 0) or 0) + row_priority
    text = (snip.text or "").strip()
    if not text:
        return
    for w in _keywords_from_text(text):
        (r["keywords"]).add(w)  # type: ignore[union-attr]
    for f in _intent_flags_from_text(text):
        (r["intent"]).add(f)  # type: ignore[union-attr]

