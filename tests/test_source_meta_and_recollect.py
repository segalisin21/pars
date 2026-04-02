"""Source Telegram metadata API and honest collect stats on re-run."""

from __future__ import annotations

from app.telegram_client import SourceTelegramMeta, TgUser


def test_refresh_telegram_meta_updates_source(client, fake_tg):
    fake_tg.source_meta_by_key["mych"] = SourceTelegramMeta(title="My Channel", participants_count=54_000)
    r = client.post("/sources", json={"type": "channel", "identifier": "@mych", "enabled": True})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    r2 = client.post(f"/sources/{sid}/refresh_telegram_meta")
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["telegram_title"] == "My Channel"
    assert body["telegram_participants_count"] == 54_000
    assert body["telegram_meta_updated_at"] is not None


def test_second_collect_increments_updated_not_new(client, fake_tg):
    s = client.post("/sources", json={"type": "group", "identifier": "@src1", "enabled": True}).json()
    fake_tg.participants_by_source["src1"] = [TgUser(tg_user_id=1, username="u1", display_name="U")]
    cr1 = client.post("/collect-runs", json={"source_ids": [s["id"]]}).json()
    assert cr1["stats"]["new_candidates"] == 1
    assert cr1["stats"]["updated_candidates"] == 0
    assert str(s["id"]) in cr1["stats"].get("by_source_id", {})

    cr2 = client.post("/collect-runs", json={"source_ids": [s["id"]]}).json()
    assert cr2["stats"]["new_candidates"] == 0
    assert cr2["stats"]["updated_candidates"] == 1
    assert cr2["stats"]["by_source_id"][str(s["id"])]["discovered"] == 1
