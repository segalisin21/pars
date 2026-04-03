from __future__ import annotations

from app.models import InviteRun, InviteTarget
from app.services import process_invite_run
from app.telegram_client import TgUser


def test_invite_resume_merges_stats_and_cursor(session_factory, fake_tg):
    db = session_factory()
    tgt = InviteTarget(workspace_id=1, identifier="@tgtw", enabled=True)
    db.add(tgt)
    db.commit()
    db.refresh(tgt)

    run = InviteRun(
        workspace_id=1,
        status="queued",
        target_id=tgt.id,
        policy={"max_per_minute": 1, "max_per_hour": 30, "cooldown_minutes": 0},
        stats={
            "attempted": 2,
            "success": 1,
            "skipped": 0,
            "failed": 0,
            "failed_by_code": {"flood_wait": 1},
            "resume_after_candidate_id": 99,
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    process_invite_run(db, fake_tg, run)
    db.commit()
    db.refresh(run)

    # No candidates in DB → completes immediately with merged cumulative stats
    assert run.status == "succeeded"
    assert run.stats["attempted"] >= 2
    assert run.stats["success"] >= 1


def test_cancel_invite_run_endpoint(client, session_factory, fake_tg):
    db = session_factory()
    t = client.post("/targets", json={"identifier": "@tgtx", "enabled": True}).json()
    run = InviteRun(
        workspace_id=1,
        status="queued",
        target_id=t["id"],
        policy={"max_per_minute": 2, "max_per_hour": 30, "cooldown_minutes": 0},
        stats={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id = run.id

    c = client.post(f"/invite-runs/{run_id}/cancel")
    assert c.status_code == 200
    body = c.json()
    assert body["status"] == "cancelled"
    assert body["stats"].get("pause_reason") == "cancelled"


def test_pacing_pause_sets_next_eligible_and_resume_cursor(client, fake_tg):
    s = client.post("/sources", json={"type": "group", "identifier": "@src_pace", "enabled": True}).json()
    t = client.post("/targets", json={"identifier": "@tgt_pace", "enabled": True}).json()
    fake_tg.participants_by_source["src_pace"] = [
        TgUser(tg_user_id=201, username="a"),
        TgUser(tg_user_id=202, username="b"),
    ]
    client.post("/collect-runs", json={"source_ids": [s["id"]]})
    ir = client.post(
        "/invite-runs",
        json={"target_id": t["id"], "policy": {"max_per_minute": 1, "max_per_hour": 30, "cooldown_minutes": 0}},
    ).json()
    assert ir["status"] == "paused"
    assert ir["stats"]["pause_reason"] == "pacing_limit"
    assert ir["stats"].get("next_eligible_at")
    assert ir["stats"].get("resume_after_candidate_id")


def test_resume_invite_run_rejects_non_paused(client, fake_tg):
    t = client.post("/targets", json={"identifier": "@tgty", "enabled": True}).json()
    r = client.post(
        "/invite-runs",
        json={"target_id": t["id"], "policy": {"max_per_minute": 2, "max_per_hour": 30, "cooldown_minutes": 0}},
    )
    assert r.status_code == 202
    run_id = r.json()["id"]
    res = client.post(f"/invite-runs/{run_id}/resume")
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "invite_run_not_resumable"
