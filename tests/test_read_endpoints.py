from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import SuppressionList, utcnow
from app.telegram_client import TgUser


def test_candidates_list_includes_sources(client, fake_tg):
    s = client.post("/sources", json={"type": "group", "identifier": "@src3", "enabled": True}).json()
    fake_tg.participants_by_source["src3"] = [
        TgUser(tg_user_id=100, username="Alpha", display_name="Alpha A"),
        TgUser(tg_user_id=101, username="Beta", display_name="Beta B"),
    ]

    client.post("/collect-runs", json={"source_ids": [s["id"]]})

    r = client.get("/candidates")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["page"]["total"] >= 2
    assert any(item["sources"] for item in body["items"])


def test_invite_attempts_list_filters(client, fake_tg):
    s = client.post("/sources", json={"type": "group", "identifier": "@src4", "enabled": True}).json()
    t = client.post("/targets", json={"identifier": "@tgt4", "enabled": True}).json()
    fake_tg.participants_by_source["src4"] = [
        TgUser(tg_user_id=200, username="Gamma", display_name="G"),
        TgUser(tg_user_id=None, username="NoId", display_name="N"),
    ]

    client.post("/collect-runs", json={"source_ids": [s["id"]]})
    client.post(
        "/invite-runs",
        json={"target_id": t["id"], "policy": {"max_per_minute": 2, "max_per_hour": 30, "cooldown_minutes": 0}},
    )

    r = client.get("/invite-attempts")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["page"]["total"] >= 1
    first_candidate_id = body["items"][0]["candidate_id"]

    r2 = client.get(f"/invite-attempts?candidate_id={first_candidate_id}")
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert all(x["candidate_id"] == first_candidate_id for x in body2["items"])


def test_suppression_list_endpoint(session_factory, client):
    db: Session = session_factory()
    try:
        db.add(
            SuppressionList(
                workspace_id=1,
                tg_user_id=999,
                username="blocked",
                reason="privacy_restricted",
                until=utcnow(),
            )
        )
        db.commit()
    finally:
        db.close()

    r = client.get("/suppression?active_only=false")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["page"]["total"] >= 1


def test_audit_events_exist_for_writes(client):
    client.post("/sources", json={"type": "group", "identifier": "@audit_src", "enabled": True})
    client.post("/targets", json={"identifier": "@audit_tgt", "enabled": True})

    r = client.get("/audit")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["page"]["total"] >= 2
    actions = {x["action"] for x in body["items"]}
    assert "source.create" in actions
    assert "target.create" in actions

