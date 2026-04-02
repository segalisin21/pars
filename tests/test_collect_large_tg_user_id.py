"""Regression: Telegram user ids may exceed 32-bit signed int; ORM uses BigInteger."""

from __future__ import annotations

from app.models import Source
from app.services import run_collect
from app.telegram_client import TgUser


def test_run_collect_persists_large_tg_user_id(session_factory, fake_tg):
    db = session_factory()
    src = Source(workspace_id=1, type="channel", identifier="@largeidtest", enabled=True)
    db.add(src)
    db.commit()
    db.refresh(src)

    large_id = 5_000_000_000  # > PostgreSQL INTEGER max; fits BigInteger
    fake_tg.participants_by_source["@largeidtest"] = [
        TgUser(tg_user_id=large_id, username="u1", display_name="U"),
    ]

    run = run_collect(db, fake_tg, [src.id], 1)
    assert run.status == "succeeded"
    assert run.stats["discovered_total"] == 1
    assert run.stats["new_candidates"] == 1
