"""Collect run modes: per-source collect_mode vs message history."""

from __future__ import annotations

from app.telegram_client import TgUser


def _patch_mode(client, source_id: int, mode: str) -> None:
    r = client.patch(f"/sources/{source_id}", json={"collect_mode": mode})
    assert r.status_code == 200, r.text


def test_collect_messages_only_uses_message_senders(client, fake_tg):
    s = client.post("/sources", json={"type": "group", "identifier": "@grpmsg", "enabled": True}).json()
    _patch_mode(client, s["id"], "messages")
    fake_tg.message_senders_by_source["grpmsg"] = [
        TgUser(tg_user_id=501, username="writer1"),
        TgUser(tg_user_id=502, username="writer2"),
    ]

    cr = client.post("/collect-runs", json={"source_ids": [s["id"]]}).json()
    assert cr["status"] == "succeeded"
    assert cr["stats"]["discovered_total"] == 2
    assert cr["stats"]["discovered_from_participants"] == 0
    assert cr["stats"]["discovered_from_messages"] == 2
    assert cr["stats"]["collect_mode"] == "messages"
    st = cr["stats"]["by_source_id"][str(s["id"])]
    assert st["collect_mode"] == "messages"
    assert st["discovered_participants"] == 0
    assert st["discovered_messages"] == 2
    assert st["discovered"] == 2
    assert cr["stats"]["new_candidates"] == 2


def test_collect_both_dedupes_user_seen_in_participants_and_messages(client, fake_tg):
    s = client.post("/sources", json={"type": "group", "identifier": "@grpboth", "enabled": True}).json()
    _patch_mode(client, s["id"], "both")
    fake_tg.participants_by_source["grpboth"] = [TgUser(tg_user_id=1, username="dup")]
    fake_tg.message_senders_by_source["grpboth"] = [
        TgUser(tg_user_id=1, username="dup"),
        TgUser(tg_user_id=2, username="only_msg"),
    ]

    cr = client.post("/collect-runs", json={"source_ids": [s["id"]]}).json()
    assert cr["status"] == "succeeded"
    assert cr["stats"]["discovered_from_participants"] == 1
    assert cr["stats"]["discovered_from_messages"] == 1
    assert cr["stats"]["discovered_total"] == 2
    assert cr["stats"]["new_candidates"] == 2


def test_collect_auto_skips_messages_when_participants_non_empty(client, fake_tg):
    s = client.post("/sources", json={"type": "group", "identifier": "@grpauto", "enabled": True}).json()
    _patch_mode(client, s["id"], "auto")
    fake_tg.participants_by_source["grpauto"] = [TgUser(tg_user_id=7, username="p")]
    fake_tg.message_senders_by_source["grpauto"] = [TgUser(tg_user_id=99, username="from_chat")]

    cr = client.post("/collect-runs", json={"source_ids": [s["id"]]}).json()
    assert cr["stats"]["discovered_from_participants"] == 1
    assert cr["stats"]["discovered_from_messages"] == 0
    assert cr["stats"]["new_candidates"] == 1


def test_collect_auto_uses_messages_when_participants_empty(client, fake_tg):
    s = client.post("/sources", json={"type": "group", "identifier": "@grpauto2", "enabled": True}).json()
    _patch_mode(client, s["id"], "auto")
    fake_tg.participants_by_source["grpauto2"] = []
    fake_tg.message_senders_by_source["grpauto2"] = [TgUser(tg_user_id=11, username="lonely")]

    cr = client.post("/collect-runs", json={"source_ids": [s["id"]]}).json()
    assert cr["stats"]["discovered_from_participants"] == 0
    assert cr["stats"]["discovered_from_messages"] == 1
    assert cr["stats"]["new_candidates"] == 1


def test_collect_message_scan_limit_truncates_fake_stream(client, fake_tg, monkeypatch):
    monkeypatch.setenv("COLLECT_MESSAGE_SCAN_LIMIT", "2")
    s = client.post("/sources", json={"type": "group", "identifier": "@grplim", "enabled": True}).json()
    _patch_mode(client, s["id"], "messages")
    fake_tg.message_senders_by_source["grplim"] = [
        TgUser(tg_user_id=1),
        TgUser(tg_user_id=2),
        TgUser(tg_user_id=3),
    ]

    cr = client.post("/collect-runs", json={"source_ids": [s["id"]]}).json()
    assert cr["stats"]["discovered_from_messages"] == 2
    assert cr["stats"]["new_candidates"] == 2


def test_source_collect_mode_overrides_env_messages(client, fake_tg, monkeypatch):
    """DB default participants wins over COLLECT_MODE=messages."""
    monkeypatch.setenv("COLLECT_MODE", "messages")
    s = client.post("/sources", json={"type": "group", "identifier": "@over", "enabled": True}).json()
    assert s.get("collect_mode") == "participants"
    fake_tg.participants_by_source["over"] = [TgUser(tg_user_id=1, username="a")]
    fake_tg.message_senders_by_source["over"] = [TgUser(tg_user_id=99, username="b")]

    cr = client.post("/collect-runs", json={"source_ids": [s["id"]]}).json()
    assert cr["stats"]["discovered_from_participants"] == 1
    assert cr["stats"]["discovered_from_messages"] == 0


def test_mixed_collect_modes_two_sources(client, fake_tg):
    a = client.post("/sources", json={"type": "group", "identifier": "@mixa", "enabled": True}).json()
    b = client.post("/sources", json={"type": "group", "identifier": "@mixb", "enabled": True}).json()
    _patch_mode(client, a["id"], "participants")
    _patch_mode(client, b["id"], "messages")
    fake_tg.participants_by_source["mixa"] = [TgUser(tg_user_id=1)]
    fake_tg.message_senders_by_source["mixb"] = [TgUser(tg_user_id=2)]

    cr = client.post("/collect-runs", json={"source_ids": [a["id"], b["id"]]}).json()
    assert cr["stats"]["collect_mode"] == "mixed"
    assert cr["stats"]["by_source_id"][str(a["id"])]["collect_mode"] == "participants"
    assert cr["stats"]["by_source_id"][str(b["id"])]["collect_mode"] == "messages"
