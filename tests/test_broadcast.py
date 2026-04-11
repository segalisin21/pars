from __future__ import annotations

from datetime import timedelta

from app.models import BroadcastRun, CandidateUser, utcnow
from app.invite_scheduler import tick_broadcast_resume
from app.services import process_broadcast_run, run_broadcast


def test_process_broadcast_sends_dm(session_factory, fake_tg):
    db = session_factory()
    c1 = CandidateUser(workspace_id=1, tg_user_id=501, username="a", display_name=None)
    c2 = CandidateUser(workspace_id=1, tg_user_id=502, username="b", display_name=None)
    db.add_all([c1, c2])
    db.commit()
    db.refresh(c1)
    db.refresh(c2)

    run = BroadcastRun(
        workspace_id=1,
        status="running",
        message_key="t1",
        message_body="hello",
        source_ids=[],
        candidate_ids=[],
        policy={"max_per_minute": 10, "max_per_hour": 100, "max_total": None},
        stats={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    process_broadcast_run(db, fake_tg, run)
    db.commit()
    db.refresh(run)

    assert run.status == "succeeded"
    assert len(fake_tg.dm_calls) == 2
    assert fake_tg.dm_calls[0][1] == "hello"
    assert int(run.stats.get("success", 0)) == 2
    db.close()


def test_broadcast_skips_already_sent_same_message_key(session_factory, fake_tg):
    db = session_factory()
    c1 = CandidateUser(workspace_id=1, tg_user_id=601, username="u601", display_name=None)
    db.add(c1)
    db.commit()
    db.refresh(c1)

    run1 = BroadcastRun(
        workspace_id=1,
        status="running",
        message_key="camp_x",
        message_body="m1",
        source_ids=[],
        candidate_ids=[c1.id],
        policy={"max_per_minute": 10, "max_per_hour": 100},
        stats={},
    )
    db.add(run1)
    db.commit()
    db.refresh(run1)
    process_broadcast_run(db, fake_tg, run1)
    db.commit()

    fake_tg.dm_calls.clear()

    run2 = BroadcastRun(
        workspace_id=1,
        status="running",
        message_key="camp_x",
        message_body="m2",
        source_ids=[],
        candidate_ids=[c1.id],
        policy={"max_per_minute": 10, "max_per_hour": 100},
        stats={},
    )
    db.add(run2)
    db.commit()
    db.refresh(run2)
    process_broadcast_run(db, fake_tg, run2)
    db.commit()
    db.refresh(run2)

    assert fake_tg.dm_calls == []
    assert int(run2.stats.get("skipped_duplicate", 0)) >= 1
    assert run2.status == "succeeded"
    db.close()


def test_run_broadcast_respects_max_total(session_factory, fake_tg):
    db = session_factory()
    for uid in (701, 702, 703):
        db.add(CandidateUser(workspace_id=1, tg_user_id=uid, username=f"u{uid}", display_name=None))
    db.commit()

    run = run_broadcast(
        db,
        fake_tg,
        1,
        message_key="cap1",
        message_body="x",
        source_ids=[],
        candidate_ids=[],
        policy={"max_per_minute": 10, "max_per_hour": 100, "max_total": 2},
        telegram_account_id=None,
    )
    db.commit()
    db.refresh(run)
    assert run.status == "succeeded"
    assert len(fake_tg.dm_calls) == 2
    assert int(run.stats.get("success", 0)) == 2
    db.close()


def test_tick_broadcast_resume_enqueues(monkeypatch, session_factory):
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
    past = utcnow() - timedelta(minutes=5)
    run = BroadcastRun(
        workspace_id=1,
        status="paused",
        message_key="k",
        message_body="b",
        source_ids=[],
        candidate_ids=[],
        policy={},
        stats={
            "pause_reason": "pacing_limit",
            "next_eligible_at": past.replace(microsecond=0).isoformat(),
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    rid = run.id
    db.close()

    n = tick_broadcast_resume()
    assert n == 1
    assert enqueued == [rid]

    db = session_factory()
    run2 = db.get(BroadcastRun, rid)
    assert run2 is not None
    assert run2.status == "queued"
    db.close()


def test_broadcast_preview_endpoint(client, session_factory):
    db = session_factory()
    c = CandidateUser(workspace_id=1, tg_user_id=801, username="p801", display_name=None)
    db.add(c)
    db.commit()
    db.refresh(c)

    r = client.post(
        "/broadcast-runs/preview",
        json={"message_key": "pv1", "source_ids": [], "candidate_ids": [c.id]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["scan_total"] == 1
    assert body["eligible"] == 1
    db.close()
