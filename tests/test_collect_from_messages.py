"""Collect run modes: participants vs message history (COLLECT_MODE)."""

from __future__ import annotations

from app.telegram_client import TgUser


def test_collect_messages_only_uses_message_senders(client, fake_tg, monkeypatch):
    monkeypatch.setenv("COLLECT_MODE", "messages")
    s = client.post("/sources", json={"type": "group", "identifier": "@grpmsg", "enabled": True}).json()
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
    assert st["discovered_participants"] == 0
    assert st["discovered_messages"] == 2
    assert st["discovered"] == 2
    assert cr["stats"]["new_candidates"] == 2


def test_collect_both_dedupes_user_seen_in_participants_and_messages(client, fake_tg, monkeypatch):
    monkeypatch.setenv("COLLECT_MODE", "both")
    s = client.post("/sources", json={"type": "group", "identifier": "@grpboth", "enabled": True}).json()
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


def test_collect_auto_skips_messages_when_participants_non_empty(client, fake_tg, monkeypatch):
    monkeypatch.setenv("COLLECT_MODE", "auto")
    s = client.post("/sources", json={"type": "group", "identifier": "@grpauto", "enabled": True}).json()
    fake_tg.participants_by_source["grpauto"] = [TgUser(tg_user_id=7, username="p")]
    fake_tg.message_senders_by_source["grpauto"] = [TgUser(tg_user_id=99, username="from_chat")]

    cr = client.post("/collect-runs", json={"source_ids": [s["id"]]}).json()
    assert cr["stats"]["discovered_from_participants"] == 1
    assert cr["stats"]["discovered_from_messages"] == 0
    assert cr["stats"]["new_candidates"] == 1


def test_collect_auto_uses_messages_when_participants_empty(client, fake_tg, monkeypatch):
    monkeypatch.setenv("COLLECT_MODE", "auto")
    s = client.post("/sources", json={"type": "group", "identifier": "@grpauto2", "enabled": True}).json()
    fake_tg.participants_by_source["grpauto2"] = []
    fake_tg.message_senders_by_source["grpauto2"] = [TgUser(tg_user_id=11, username="lonely")]

    cr = client.post("/collect-runs", json={"source_ids": [s["id"]]}).json()
    assert cr["stats"]["discovered_from_participants"] == 0
    assert cr["stats"]["discovered_from_messages"] == 1
    assert cr["stats"]["new_candidates"] == 1


def test_collect_message_scan_limit_truncates_fake_stream(client, fake_tg, monkeypatch):
    monkeypatch.setenv("COLLECT_MODE", "messages")
    monkeypatch.setenv("COLLECT_MESSAGE_SCAN_LIMIT", "2")
    s = client.post("/sources", json={"type": "group", "identifier": "@grplim", "enabled": True}).json()
    fake_tg.message_senders_by_source["grplim"] = [
        TgUser(tg_user_id=1),
        TgUser(tg_user_id=2),
        TgUser(tg_user_id=3),
    ]

    cr = client.post("/collect-runs", json={"source_ids": [s["id"]]}).json()
    assert cr["stats"]["discovered_from_messages"] == 2
    assert cr["stats"]["new_candidates"] == 2
