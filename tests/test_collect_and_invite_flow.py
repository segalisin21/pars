from __future__ import annotations

from app.telegram_client import TgUser


def test_collect_run_persists_candidates_and_invite_uses_tg_ids(client, fake_tg):
    # Create source and target
    s = client.post("/sources", json={"type": "group", "identifier": "@src1", "enabled": True}).json()
    t = client.post("/targets", json={"identifier": "@tgt1", "enabled": True}).json()

    # Configure fake participants for this source
    fake_tg.participants_by_source["src1"] = [
        TgUser(tg_user_id=1, username="UserOne", display_name="U1"),
        TgUser(tg_user_id=2, username=None, display_name="U2"),
    ]

    # Run collect
    cr = client.post("/collect-runs", json={"source_ids": [s["id"]]}).json()
    assert cr["status"] == "succeeded"
    assert cr["stats"]["discovered_total"] == 2

    # Run invite (should invite only candidates with tg_user_id)
    ir = client.post("/invite-runs", json={"target_id": t["id"], "policy": {"max_per_minute": 2, "max_per_hour": 30, "cooldown_minutes": 0}}).json()
    assert ir["status"] == "succeeded"
    assert ir["stats"]["attempted"] >= 2
    assert ("tgt1", 1) in fake_tg.invite_calls
    assert ("tgt1", 2) in fake_tg.invite_calls


def test_invite_flood_wait_is_recorded_in_stats(client, fake_tg):
    s = client.post("/sources", json={"type": "group", "identifier": "@src2", "enabled": True}).json()
    t = client.post("/targets", json={"identifier": "@tgt2", "enabled": True}).json()

    fake_tg.participants_by_source["src2"] = [
        TgUser(tg_user_id=10, username="ten"),
        TgUser(tg_user_id=11, username="eleven"),
    ]
    fake_tg.flood_on_user_ids.add(11)

    client.post("/collect-runs", json={"source_ids": [s["id"]]})
    ir = client.post("/invite-runs", json={"target_id": t["id"], "policy": {"max_per_minute": 2, "max_per_hour": 30, "cooldown_minutes": 0}}).json()
    assert ir["stats"]["failed_by_code"].get("flood_wait", 0) == 1

