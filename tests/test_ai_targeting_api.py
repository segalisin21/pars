from __future__ import annotations

import json


def test_targeting_profiles_list_empty(client):
    r = client.get("/targeting/profiles")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []


def test_targeting_ai_suggest_requires_key(client, monkeypatch):
    # Ensure env key not set inside test.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = client.post("/targeting/ai/suggest", json={"query": "селлеры маркетплейсов", "language_mode": "ru"})
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == "openai_not_configured"


def test_targeting_profile_preview_empty_when_no_features(client, session_factory):
    # Preview with no computed CandidateFeatures for profile should return empty.
    r = client.post("/targeting/profiles/preview", json={"profile_id": 999, "segment": "any", "limit": 50})
    assert r.status_code == 200
    body = r.json()
    assert body["top"] == []

