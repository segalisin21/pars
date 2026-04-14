from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import CandidateFeatures, CandidateSourceLink, CandidateUser, Source
from app.targeting import recompute_candidate_features
from app.telegram_client import TgMessageSnippet, TgUser


def test_recompute_candidate_features_builds_segments(session_factory, fake_tg):
    db = session_factory()
    # Source
    src = Source(workspace_id=1, type="group", identifier="src_t", enabled=True, notes=None, collect_mode="messages")
    db.add(src)
    db.commit()
    db.refresh(src)
    # Candidate + link
    c = CandidateUser(workspace_id=1, tg_user_id=123, username="u123", display_name="Name", last_seen_at=datetime.now(timezone.utc))
    db.add(c)
    db.commit()
    db.refresh(c)
    db.add(CandidateSourceLink(workspace_id=1, candidate_id=c.id, source_id=src.id))
    db.commit()

    fake_tg.message_snippets_by_source["src_t"] = [
        TgMessageSnippet(sender=TgUser(tg_user_id=123, username="u123", display_name="Name"), text="Ищу рекомендацию по теме", date=datetime.now(timezone.utc))
    ]

    n = recompute_candidate_features(db, fake_tg, workspace_id=1)
    db.commit()
    assert n >= 1
    row = db.scalar(select(CandidateFeatures).where(CandidateFeatures.workspace_id == 1, CandidateFeatures.candidate_id == c.id))
    assert row is not None
    assert row.segment in {"A", "B", "C"}
    assert row.send_score == row.warmth_score - row.risk_score
    assert "seek" in set(row.intent_flags)
    db.close()


