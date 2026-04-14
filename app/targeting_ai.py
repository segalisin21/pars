from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CandidateEmbedding, CandidateFeatures, CandidateMessage, CandidateSourceLink, CandidateUser, Source, TargetingProfile, utcnow
from app.openai_client import embed_texts
from app.services import effective_collect_mode_for_source, normalize_username
from app.telegram_client import TelegramClient, TgMessageSnippet


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _dt_utc(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    if v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


def capture_messages_for_workspace(
    db: Session,
    tg: TelegramClient,
    *,
    workspace_id: int,
    min_date: datetime,
    max_messages_per_source: int,
) -> int:
    """Pull message snippets from enabled sources and store into candidate_messages with dedupe."""
    sources = db.scalars(select(Source).where(Source.workspace_id == workspace_id, Source.enabled.is_(True))).all()
    inserted = 0
    for src in sources:
        ident = (src.identifier or "").strip()
        mode = effective_collect_mode_for_source(src)
        if mode not in {"messages", "both", "auto"}:
            continue
        for snip in tg.iter_message_snippets(ident, limit=max_messages_per_source, min_date=min_date):
            sender = snip.sender
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
                continue
            txt = (snip.text or "").strip()
            if not txt:
                continue
            h = _sha256(txt)
            row = CandidateMessage(
                workspace_id=workspace_id,
                source_id=int(src.id),
                candidate_id=int(cand.id),
                msg_date=_dt_utc(snip.date),
                text=txt,
                text_hash=h,
                created_at=utcnow(),
            )
            try:
                with db.begin_nested():
                    db.add(row)
                    db.flush()
                inserted += 1
            except IntegrityError:
                continue
    db.flush()
    return inserted


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _extract_profile_terms(params: dict) -> tuple[list[str], list[str]]:
    inc = params.get("keywords_include")
    exc = params.get("keywords_exclude")
    include = [str(x).strip().lower() for x in inc] if isinstance(inc, list) else []
    exclude = [str(x).strip().lower() for x in exc] if isinstance(exc, list) else []
    include = [x for x in include if 2 <= len(x) <= 40][:60]
    exclude = [x for x in exclude if 2 <= len(x) <= 40][:60]
    return include, exclude


def _candidate_text(db: Session, workspace_id: int, candidate_id: int, *, max_chars: int = 4000) -> str:
    rows = db.scalars(
        select(CandidateMessage.text)
        .where(CandidateMessage.workspace_id == workspace_id, CandidateMessage.candidate_id == candidate_id)
        .order_by(CandidateMessage.id.desc())
        .limit(50)
    ).all()
    parts: list[str] = []
    total = 0
    for t in rows:
        s = (t or "").strip()
        if not s:
            continue
        if total + len(s) + 1 > max_chars:
            break
        parts.append(s)
        total += len(s) + 1
    return "\n".join(parts)


def recompute_features_for_profile(db: Session, *, workspace_id: int, profile: TargetingProfile) -> int:
    """Compute CandidateFeatures.targeting_profile_id + semantic_score for profile query using cached messages."""
    params = profile.params if isinstance(profile.params, dict) else {}
    include, exclude = _extract_profile_terms(params)
    # Query embedding (OpenAI).
    emb_q = embed_texts(model="text-embedding-3-small", inputs=[profile.query])[0]

    candidates = db.scalars(select(CandidateUser).where(CandidateUser.workspace_id == workspace_id)).all()
    up = 0
    now = utcnow()
    for cand in candidates:
        # quick keyword gate
        text = _candidate_text(db, workspace_id, cand.id)
        if not text:
            continue
        low = text.lower()
        if include and not any(k in low for k in include):
            continue
        if exclude and any(k in low for k in exclude):
            continue

        # Candidate embedding cache
        ce = db.scalar(
            select(CandidateEmbedding).where(CandidateEmbedding.workspace_id == workspace_id, CandidateEmbedding.candidate_id == cand.id)
        )
        if ce is None or not isinstance(ce.vector, list) or len(ce.vector) == 0:
            vec = embed_texts(model="text-embedding-3-small", inputs=[text])[0]
            if ce is None:
                ce = CandidateEmbedding(workspace_id=workspace_id, candidate_id=cand.id, model="text-embedding-3-small", vector=vec)
                db.add(ce)
            else:
                ce.vector = vec
                ce.model = "text-embedding-3-small"
            ce.updated_at = now
        sim = _cosine(emb_q, [float(x) for x in (ce.vector or [])])
        semantic = int(max(0.0, min(1.0, (sim + 1.0) / 2.0)) * 1000.0)

        # Upsert CandidateFeatures row (reuse current warmth/risk if exists, else minimal).
        cf = db.scalar(
            select(CandidateFeatures).where(CandidateFeatures.workspace_id == workspace_id, CandidateFeatures.candidate_id == cand.id)
        )
        if cf is None:
            cf = CandidateFeatures(workspace_id=workspace_id, candidate_id=cand.id)
            db.add(cf)
        cf.targeting_profile_id = int(profile.id)
        cf.semantic_score = int(semantic)
        # Combine into send_score conservatively.
        base = int(cf.warmth_score) - int(cf.risk_score)
        cf.send_score = int(base + (semantic // 20))  # 0..50 added
        cf.segment = "A" if cf.send_score >= 40 else ("B" if cf.send_score >= 10 else "C")
        rs = cf.reasons if isinstance(cf.reasons, dict) else {}
        rs.update({"semantic_score": semantic, "profile_id": int(profile.id)})
        cf.reasons = rs
        cf.computed_at = now
        up += 1

    db.flush()
    return up

