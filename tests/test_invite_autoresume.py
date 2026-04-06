from __future__ import annotations

from datetime import timedelta

from app.invite_scheduler import tick_invite_resume
from app.models import InviteRun, InviteTarget, utcnow


def test_tick_invite_resume_enqueues_eligible_paused(monkeypatch, session_factory):
    monkeypatch.setattr("app.invite_scheduler.get_worker_session_factory", lambda: session_factory)
    monkeypatch.setattr("app.invite_scheduler.is_queue_enabled", lambda: True)
    enqueued: list[int] = []

    class Q:
        def enqueue(self, fn, **kwargs):
            rid = kwargs.get("run_id")
            if rid is not None:
                enqueued.append(int(rid))

    monkeypatch.setattr("app.invite_scheduler.get_rq_queue", lambda: Q())

    db = session_factory()
    tgt = InviteTarget(workspace_id=1, identifier="@tgt_tick", enabled=True)
    db.add(tgt)
    db.commit()
    db.refresh(tgt)

    past = utcnow() - timedelta(minutes=5)
    run = InviteRun(
        workspace_id=1,
        status="paused",
        target_id=tgt.id,
        policy={"max_per_minute": 2, "max_per_hour": 30, "cooldown_minutes": 0},
        stats={
            "pause_reason": "pacing_limit",
            "next_eligible_at": past.replace(microsecond=0).isoformat(),
            "attempted": 2,
            "success": 1,
            "skipped": 0,
            "failed": 0,
            "failed_by_code": {},
            "resume_after_candidate_id": 1,
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    rid = run.id
    db.close()

    n = tick_invite_resume()
    assert n == 1
    assert enqueued == [rid]

    db = session_factory()
    run2 = db.get(InviteRun, rid)
    assert run2 is not None
    assert run2.status == "queued"
    db.close()


def test_tick_invite_resume_skips_future(monkeypatch, session_factory):
    monkeypatch.setattr("app.invite_scheduler.get_worker_session_factory", lambda: session_factory)
    monkeypatch.setattr("app.invite_scheduler.is_queue_enabled", lambda: True)
    monkeypatch.setattr(
        "app.invite_scheduler.get_rq_queue",
        lambda: type("Q", (), {"enqueue": lambda *a, **k: None})(),
    )

    db = session_factory()
    tgt = InviteTarget(workspace_id=1, identifier="@tgt_future", enabled=True)
    db.add(tgt)
    db.commit()
    db.refresh(tgt)

    future = utcnow() + timedelta(hours=1)
    run = InviteRun(
        workspace_id=1,
        status="paused",
        target_id=tgt.id,
        policy={"max_per_minute": 2, "max_per_hour": 30, "cooldown_minutes": 0},
        stats={
            "pause_reason": "flood_wait",
            "next_eligible_at": future.isoformat(),
        },
    )
    db.add(run)
    db.commit()
    db.close()

    assert tick_invite_resume() == 0
