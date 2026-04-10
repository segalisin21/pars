from __future__ import annotations

import csv
import io

from app.models import CandidateUser, InviteAttempt, InviteRun, InviteTarget
from app.telegram_client import TgUser


def test_invite_max_invites_stops_after_n_successes(client, fake_tg):
    s = client.post("/sources", json={"type": "group", "identifier": "@src_cap", "enabled": True}).json()
    t = client.post("/targets", json={"identifier": "@tgt_cap", "enabled": True}).json()
    fake_tg.participants_by_source["src_cap"] = [
        TgUser(tg_user_id=301, username="a"),
        TgUser(tg_user_id=302, username="b"),
        TgUser(tg_user_id=303, username="c"),
    ]
    assert client.post("/collect-runs", json={"source_ids": [s["id"]]}).json()["status"] == "succeeded"

    ir = client.post(
        "/invite-runs",
        json={
            "target_id": t["id"],
            "policy": {"max_per_minute": 10, "max_per_hour": 1000, "cooldown_minutes": 0, "max_invites": 2},
        },
    ).json()
    assert ir["status"] == "succeeded"
    assert ir["stats"]["success"] == 2
    assert ir["stats"]["stop_reason"] == "invite_cap_reached"
    assert ir["stats"]["max_invites_cap"] == 2
    assert len(fake_tg.invite_calls) == 2
    assert {x[1] for x in fake_tg.invite_calls} == {301, 302}


def test_invite_without_max_invites_invites_all_with_tg_id(client, fake_tg):
    s = client.post("/sources", json={"type": "group", "identifier": "@src_nocap", "enabled": True}).json()
    t = client.post("/targets", json={"identifier": "@tgt_nocap", "enabled": True}).json()
    fake_tg.participants_by_source["src_nocap"] = [
        TgUser(tg_user_id=401, username="x"),
        TgUser(tg_user_id=402, username="y"),
        TgUser(tg_user_id=403, username="z"),
    ]
    assert client.post("/collect-runs", json={"source_ids": [s["id"]]}).json()["status"] == "succeeded"

    ir = client.post(
        "/invite-runs",
        json={
            "target_id": t["id"],
            "policy": {"max_per_minute": 10, "max_per_hour": 1000, "cooldown_minutes": 0},
        },
    ).json()
    assert ir["status"] == "succeeded"
    assert ir["stats"]["success"] == 3
    assert "stop_reason" not in ir["stats"]
    assert len(fake_tg.invite_calls) == 3


def test_invite_max_invites_resumes_until_cap(client, fake_tg):
    s = client.post("/sources", json={"type": "group", "identifier": "@src_rcap", "enabled": True}).json()
    t = client.post("/targets", json={"identifier": "@tgt_rcap", "enabled": True}).json()
    fake_tg.participants_by_source["src_rcap"] = [
        TgUser(tg_user_id=501, username="a"),
        TgUser(tg_user_id=502, username="b"),
        TgUser(tg_user_id=503, username="c"),
    ]
    assert client.post("/collect-runs", json={"source_ids": [s["id"]]}).json()["status"] == "succeeded"

    ir1 = client.post(
        "/invite-runs",
        json={
            "target_id": t["id"],
            "policy": {"max_per_minute": 1, "max_per_hour": 1000, "cooldown_minutes": 0, "max_invites": 2},
        },
    ).json()
    assert ir1["status"] == "paused"
    assert ir1["stats"]["success"] == 1
    assert ir1["stats"]["pause_reason"] == "pacing_limit"

    run_id = ir1["id"]
    ir2 = client.post(f"/invite-runs/{run_id}/resume").json()
    assert ir2["status"] == "succeeded"
    assert ir2["stats"]["success"] == 2
    assert ir2["stats"]["stop_reason"] == "invite_cap_reached"
    assert len(fake_tg.invite_calls) == 2


def test_export_deferred_csv_filters_codes(client, session_factory):
    db = session_factory()
    tgt = InviteTarget(workspace_id=1, identifier="ex_tgt", enabled=True)
    db.add(tgt)
    db.commit()
    db.refresh(tgt)

    c1 = CandidateUser(workspace_id=1, tg_user_id=9001, username="u1")
    c2 = CandidateUser(workspace_id=1, tg_user_id=9002, username="u2")
    db.add_all([c1, c2])
    db.commit()
    db.refresh(c1)
    db.refresh(c2)

    run = InviteRun(
        workspace_id=1,
        status="succeeded",
        target_id=tgt.id,
        policy={},
        stats={},
        source_ids=[],
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    db.add_all(
        [
            InviteAttempt(
                workspace_id=1,
                invite_run_id=run.id,
                target_id=tgt.id,
                candidate_id=c1.id,
                status="failed",
                error_code="privacy_restricted",
            ),
            InviteAttempt(
                workspace_id=1,
                invite_run_id=run.id,
                target_id=tgt.id,
                candidate_id=c2.id,
                status="failed",
                error_code="unknown",
            ),
        ]
    )
    db.commit()

    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import FakeTelegramClient

    fake_tg = FakeTelegramClient()
    app = create_app(session_factory=session_factory, tg_client=fake_tg)
    tc = TestClient(app)
    r = tc.get(f"/invite-runs/{run.id}/export-deferred")
    assert r.status_code == 200, r.text
    assert r.headers.get("content-type", "").startswith("text/csv")

    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == ["candidate_id", "tg_user_id", "username", "error_code"]
    assert len(rows) == 2
    assert rows[1][0] == str(c1.id)
    assert rows[1][3] == "privacy_restricted"


def test_invite_policy_rejects_max_invites_out_of_range(client, fake_tg):
    t = client.post("/targets", json={"identifier": "@tgt_badcap", "enabled": True}).json()
    r = client.post(
        "/invite-runs",
        json={
            "target_id": t["id"],
            "policy": {"max_per_minute": 2, "max_per_hour": 30, "cooldown_minutes": 0, "max_invites": 0},
        },
    )
    assert r.status_code == 422
