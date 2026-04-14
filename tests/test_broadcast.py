from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import (
    BroadcastDelivery,
    BroadcastRun,
    CandidateFeatures,
    CandidateProfileFeatures,
    CandidateUser,
    TargetingProfile,
    utcnow,
)
from app.invite_scheduler import tick_broadcast_resume
from app.services import _classify_dm_error, process_broadcast_run, run_broadcast


def test_classify_dm_peer_flood_and_not_mutual():
    class PeerFloodError(Exception):
        pass

    class UserNotMutualContactError(Exception):
        pass

    assert _classify_dm_error(PeerFloodError()) == "peer_flood"
    assert _classify_dm_error(UserNotMutualContactError()) == "not_mutual_contact"


def test_process_broadcast_outbox_verify_passes(session_factory, fake_tg):
    db = session_factory()
    c = CandidateUser(workspace_id=1, tg_user_id=6011, username="v1", display_name=None)
    db.add(c)
    db.commit()
    db.refresh(c)
    run = BroadcastRun(
        workspace_id=1,
        status="running",
        message_key="ov_ok",
        message_body="x",
        source_ids=[],
        candidate_ids=[c.id],
        policy={"max_per_minute": 10, "max_per_hour": 100, "verify_outbox_after_send": True},
        stats={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    process_broadcast_run(db, fake_tg, run)
    db.commit()
    db.refresh(run)
    assert run.status == "succeeded"
    assert int(run.stats.get("success", 0)) == 1
    row = db.scalars(select(BroadcastDelivery).where(BroadcastDelivery.broadcast_run_id == run.id)).one()
    assert row.status == "success"
    assert row.telegram_message_id == 1
    assert row.error_code is None
    db.close()


def test_process_broadcast_outbox_verify_fails(session_factory, fake_tg):
    fake_tg.outbox_verify_fail_message_ids.add(1)
    db = session_factory()
    c = CandidateUser(workspace_id=1, tg_user_id=6012, username="v2", display_name=None)
    db.add(c)
    db.commit()
    db.refresh(c)
    run = BroadcastRun(
        workspace_id=1,
        status="running",
        message_key="ov_bad",
        message_body="x",
        source_ids=[],
        candidate_ids=[c.id],
        policy={"max_per_minute": 10, "max_per_hour": 100, "verify_outbox_after_send": True},
        stats={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    process_broadcast_run(db, fake_tg, run)
    db.commit()
    db.refresh(run)
    assert run.status == "succeeded"
    assert int(run.stats.get("failed", 0)) == 1
    assert int(run.stats.get("success", 0)) == 0
    row = db.scalars(select(BroadcastDelivery).where(BroadcastDelivery.broadcast_run_id == run.id)).one()
    assert row.status == "failed"
    assert row.error_code == "outbox_verify_failed"
    assert row.telegram_message_id == 1
    db.close()


def test_process_broadcast_verify_skipped_when_client_no_support(session_factory, fake_tg, monkeypatch):
    monkeypatch.setattr(fake_tg, "supports_outbox_verify", lambda *args, **kwargs: False)

    db = session_factory()
    c = CandidateUser(workspace_id=1, tg_user_id=6013, username="v3", display_name=None)
    db.add(c)
    db.commit()
    db.refresh(c)
    run = BroadcastRun(
        workspace_id=1,
        status="running",
        message_key="ov_skip",
        message_body="x",
        source_ids=[],
        candidate_ids=[c.id],
        policy={"max_per_minute": 10, "max_per_hour": 100, "verify_outbox_after_send": True},
        stats={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    process_broadcast_run(db, fake_tg, run)
    db.commit()
    db.refresh(run)
    assert int(run.stats.get("success", 0)) == 1
    row = db.scalars(select(BroadcastDelivery).where(BroadcastDelivery.broadcast_run_id == run.id)).one()
    assert row.status == "success"
    assert row.telegram_message_id == 1
    db.close()


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
    assert fake_tg.dm_calls[0][0] == "tg_user_id"
    assert fake_tg.dm_calls[0][1] == 501
    assert fake_tg.dm_calls[0][2] == "hello"
    assert int(run.stats.get("success", 0)) == 2
    rows = db.scalars(select(BroadcastDelivery).where(BroadcastDelivery.broadcast_run_id == run.id)).all()
    assert {r.telegram_message_id for r in rows} == {1, 2}
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


def test_broadcast_pacing_counts_failed_send_attempts(session_factory, fake_tg, monkeypatch):
    """max_per_minute applies to every send_direct_message call, not only successes."""
    db = session_factory()
    for uid in (910, 911, 912, 913):
        db.add(CandidateUser(workspace_id=1, tg_user_id=uid, username=f"u{uid}", display_name=None))
    db.commit()

    def _always_fail(
        text: str,
        *,
        tg_user_id: int | None = None,
        username: str | None = None,
    ) -> None:
        if tg_user_id is not None:
            fake_tg.dm_calls.append(("tg_user_id", int(tg_user_id), text))
        else:
            fake_tg.dm_calls.append(("username", str(username or ""), text))
        raise RuntimeError("simulated send failure")

    monkeypatch.setattr(fake_tg, "send_direct_message", _always_fail)

    run = BroadcastRun(
        workspace_id=1,
        status="running",
        message_key="pace_fail",
        message_body="x",
        source_ids=[],
        candidate_ids=[],
        policy={"max_per_minute": 2, "max_per_hour": 100, "max_total": None},
        stats={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    process_broadcast_run(db, fake_tg, run)
    db.commit()
    db.refresh(run)

    assert run.status == "paused"
    assert run.stats.get("pause_reason") == "pacing_limit"
    assert len(fake_tg.dm_calls) == 2
    assert int(run.stats.get("attempted", 0)) == 2
    assert int(run.stats.get("failed", 0)) == 2
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
    assert body["missing_username"] == 0
    db.close()


def test_broadcast_preview_eligible_without_username(client, session_factory):
    db = session_factory()
    c = CandidateUser(workspace_id=1, tg_user_id=802, username=None, display_name=None)
    db.add(c)
    db.commit()
    db.refresh(c)

    r = client.post(
        "/broadcast-runs/preview",
        json={"message_key": "pv_no_u", "source_ids": [], "candidate_ids": [c.id]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["eligible"] == 1
    assert body["missing_tg_user_id"] == 0
    assert body["missing_username"] == 0
    db.close()


def test_process_broadcast_username_mode_uses_username_peer(session_factory, fake_tg):
    db = session_factory()
    c = CandidateUser(workspace_id=1, tg_user_id=55_001, username="SomeUser", display_name=None)
    db.add(c)
    db.commit()
    db.refresh(c)
    run = BroadcastRun(
        workspace_id=1,
        status="running",
        message_key="un_mode",
        message_body="hi",
        source_ids=[],
        candidate_ids=[c.id],
        policy={"max_per_minute": 10, "max_per_hour": 100, "dm_recipient": "username"},
        stats={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    process_broadcast_run(db, fake_tg, run)
    db.commit()
    db.refresh(run)
    assert run.status == "succeeded"
    assert len(fake_tg.dm_calls) == 1
    assert fake_tg.dm_calls[0][0] == "username"
    assert fake_tg.dm_calls[0][1] == "someuser"
    assert fake_tg.dm_calls[0][2] == "hi"
    row = db.scalars(select(BroadcastDelivery).where(BroadcastDelivery.broadcast_run_id == run.id)).one()
    assert row.status == "success"
    assert row.tg_user_id == 55_001
    db.close()


def test_process_broadcast_username_mode_skips_without_username(session_factory, fake_tg):
    db = session_factory()
    c = CandidateUser(workspace_id=1, tg_user_id=55_002, username=None, display_name=None)
    db.add(c)
    db.commit()
    db.refresh(c)
    run = BroadcastRun(
        workspace_id=1,
        status="running",
        message_key="no_un",
        message_body="x",
        source_ids=[],
        candidate_ids=[c.id],
        policy={"max_per_minute": 10, "max_per_hour": 100, "dm_recipient": "username"},
        stats={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    process_broadcast_run(db, fake_tg, run)
    db.commit()
    db.refresh(run)
    assert fake_tg.dm_calls == []
    assert int(run.stats.get("skipped", 0)) >= 1
    db.close()


def test_broadcast_preview_username_mode_counts_missing_username(client, session_factory):
    db = session_factory()
    c = CandidateUser(workspace_id=1, tg_user_id=803, username=None, display_name=None)
    db.add(c)
    db.commit()
    db.refresh(c)
    r = client.post(
        "/broadcast-runs/preview",
        json={"message_key": "pv_un", "source_ids": [], "candidate_ids": [c.id], "dm_recipient": "username"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["missing_username"] == 1
    assert body["eligible"] == 0
    assert body["missing_tg_user_id"] == 0
    db.close()


def test_broadcast_duplicate_when_no_tg_user_id_uses_candidate(session_factory, fake_tg):
    db = session_factory()
    c = CandidateUser(workspace_id=1, tg_user_id=None, username="onlyname", display_name=None)
    db.add(c)
    db.commit()
    db.refresh(c)
    run1 = BroadcastRun(
        workspace_id=1,
        status="running",
        message_key="cid_dup",
        message_body="m1",
        source_ids=[],
        candidate_ids=[c.id],
        policy={"max_per_minute": 10, "max_per_hour": 100, "dm_recipient": "username"},
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
        message_key="cid_dup",
        message_body="m2",
        source_ids=[],
        candidate_ids=[c.id],
        policy={"max_per_minute": 10, "max_per_hour": 100, "dm_recipient": "username"},
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
    db.close()


def test_targeting_preview_endpoint_empty_when_no_features(client):
    r = client.post("/broadcast-runs/targeting-preview", json={"source_ids": [], "candidate_ids": [], "segment": "any", "limit": 50})
    assert r.status_code == 200
    body = r.json()
    assert body["top"] == []



def test_list_broadcast_deliveries(client, session_factory):
    db = session_factory()
    c = CandidateUser(workspace_id=1, tg_user_id=9001, username=None, display_name="Nick")
    db.add(c)
    db.commit()
    db.refresh(c)
    run = BroadcastRun(
        workspace_id=1,
        status="succeeded",
        message_key="kdel",
        message_body="hi",
        source_ids=[],
        candidate_ids=[],
        policy={},
        stats={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    db.add(
        BroadcastDelivery(
            workspace_id=1,
            broadcast_run_id=run.id,
            message_key="kdel",
            candidate_id=c.id,
            tg_user_id=9001,
            status="success",
            error_code=None,
        )
    )
    db.commit()
    rid = run.id
    db.close()

    r = client.get(f"/broadcast-runs/{rid}/deliveries")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["page"]["total"] == 1
    assert body["items"][0]["tg_user_id"] == 9001
    assert body["items"][0]["username"] is None
    assert body["items"][0]["display_name"] == "Nick"
    assert body["items"][0]["status"] == "success"

    r2 = client.get(f"/broadcast-runs/{rid}/deliveries?status=success")
    assert r2.status_code == 200
    assert r2.json()["page"]["total"] == 1


def test_patch_broadcast_message_body_paused(client, session_factory):
    db = session_factory()
    run = BroadcastRun(
        workspace_id=1,
        status="paused",
        message_key="kp",
        message_body="old",
        source_ids=[],
        candidate_ids=[],
        policy={},
        stats={"pause_reason": "pacing_limit"},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    rid = run.id
    db.close()

    r = client.patch(f"/broadcast-runs/{rid}", json={"message_body": "new body text"})
    assert r.status_code == 200, r.text
    assert r.json()["message_body"] == "new body text"


def test_patch_broadcast_message_body_rejects_succeeded(client, session_factory):
    db = session_factory()
    run = BroadcastRun(
        workspace_id=1,
        status="succeeded",
        message_key="ks",
        message_body="x",
        source_ids=[],
        candidate_ids=[],
        policy={},
        stats={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    rid = run.id
    db.close()

    r = client.patch(f"/broadcast-runs/{rid}", json={"message_body": "y"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "broadcast_run_not_editable"


def test_broadcast_targeting_profile_id_filters_by_profile_features(session_factory, fake_tg):
    db = session_factory()
    c = CandidateUser(workspace_id=1, tg_user_id=9901, username="u9901", display_name=None)
    db.add(c)
    db.commit()
    db.refresh(c)

    prof = TargetingProfile(
        workspace_id=1,
        name="p",
        query="q",
        language_mode="mixed",
        params={
            "version": "v2",
            "limits": {"days": 14, "max_messages_per_source": 10, "max_candidate_text_chars": 4000, "max_candidates": None},
            "terms": {"keywords_include": [], "keywords_exclude": [], "intent_phrases": []},
            "weights": {"semantic": 1, "warmth": 1, "risk": 1},
            "thresholds": {"min_send_score": 10, "segment_a_min": 40, "segment_b_min": 10},
            "models": {"embedding_model": "text-embedding-3-small"},
        },
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(prof)
    db.commit()
    db.refresh(prof)

    db.add(
        CandidateFeatures(
            workspace_id=1,
            candidate_id=c.id,
            segment="C",
            send_score=0,
            warmth_score=0,
            risk_score=0,
            reasons={},
        )
    )
    db.add(
        CandidateProfileFeatures(
            workspace_id=1,
            candidate_id=c.id,
            targeting_profile_id=prof.id,
            segment="A",
            send_score=100,
            warmth_score=50,
            risk_score=0,
            semantic_score=800,
            reasons={"semantic_score": 800},
        )
    )
    db.commit()

    run = BroadcastRun(
        workspace_id=1,
        status="running",
        message_key="tpid",
        message_body="hello",
        source_ids=[],
        candidate_ids=[c.id],
        policy={"max_per_minute": 10, "max_per_hour": 100, "targeting_profile_id": prof.id, "targeting_segment": "A"},
        stats={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    process_broadcast_run(db, fake_tg, run)
    db.commit()
    assert len(fake_tg.dm_calls) == 1
    db.close()
