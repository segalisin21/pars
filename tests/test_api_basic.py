from __future__ import annotations


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_sources_create_and_list(client):
    r = client.post("/sources", json={"type": "group", "identifier": "@SomeGroup", "enabled": True})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] >= 1
    assert body["type"] == "group"
    assert body["identifier"] == "SomeGroup"

    r2 = client.get("/sources")
    assert r2.status_code == 200
    items = r2.json()["items"]
    assert len(items) == 1
    assert items[0]["identifier"] == "SomeGroup"


def test_targets_create_and_list(client):
    r = client.post("/targets", json={"identifier": "@TargetGroup", "enabled": True})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["identifier"] == "TargetGroup"

    r2 = client.get("/targets")
    assert r2.status_code == 200
    items = r2.json()["items"]
    assert len(items) == 1
    assert items[0]["identifier"] == "TargetGroup"


def test_collect_run_unknown_source_returns_404(client):
    r = client.post("/collect-runs", json={"source_ids": [999]})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "source_not_found"


def test_invite_run_unknown_target_returns_404(client):
    r = client.post("/invite-runs", json={"target_id": 999, "policy": {"max_per_minute": 2, "max_per_hour": 30, "cooldown_minutes": 0}})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "target_not_found"

