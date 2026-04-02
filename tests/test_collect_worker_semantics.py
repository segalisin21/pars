from __future__ import annotations

from sqlalchemy import func, select

from app.models import CollectRun, InviteRun, InviteTarget, Source
from app.services import process_collect_run, process_invite_run
from app.telegram_client import TgUser


def test_process_collect_run_updates_existing_run(session_factory, fake_tg):
    db = session_factory()
    src = Source(workspace_id=1, type="group", identifier="@srcw", enabled=True)
    db.add(src)
    db.commit()
    db.refresh(src)

    run = CollectRun(workspace_id=1, status="queued", source_ids=[src.id], stats={})
    db.add(run)
    db.commit()
    db.refresh(run)

    fake_tg.participants_by_source["@srcw"] = [
        TgUser(tg_user_id=1, username="u1"),
        TgUser(tg_user_id=2, username="u2"),
    ]

    before_runs = db.scalar(select(func.count(CollectRun.id)))
    process_collect_run(db, fake_tg, run)
    db.commit()
    after_runs = db.scalar(select(func.count(CollectRun.id)))

    assert before_runs == after_runs
    db.refresh(run)
    assert run.status == "succeeded"
    assert run.stats["discovered_total"] == 2
    assert run.stats["discovered_from_participants"] == 2
    assert run.stats["discovered_from_messages"] == 0
    assert run.stats.get("collect_mode") == "participants"


def test_process_invite_run_updates_existing_run(session_factory, fake_tg):
    db = session_factory()
    tgt = InviteTarget(workspace_id=1, identifier="@tgtw", enabled=True)
    db.add(tgt)
    db.commit()
    db.refresh(tgt)

    run = InviteRun(
        workspace_id=1,
        status="queued",
        target_id=tgt.id,
        policy={"cooldown_minutes": 0},
        stats={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    before_runs = db.scalar(select(func.count(InviteRun.id)))
    process_invite_run(db, fake_tg, run)
    db.commit()
    after_runs = db.scalar(select(func.count(InviteRun.id)))

    assert before_runs == after_runs
    db.refresh(run)
    assert run.status in {"succeeded", "paused"}

