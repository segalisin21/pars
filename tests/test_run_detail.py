"""Regression: GET detail endpoints return 404 for unknown ids or wrong workspace."""

from __future__ import annotations


def test_get_collect_run_unknown_returns_404(client):
    r = client.get("/collect-runs/999999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "collect_run_not_found"


def test_get_invite_run_unknown_returns_404(client):
    r = client.get("/invite-runs/999999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "invite_run_not_found"


def test_get_collect_run_other_workspace_returns_404(client, fake_tg):
    s = client.post("/sources", json={"type": "group", "identifier": "@iso_src", "enabled": True}).json()
    cr = client.post("/collect-runs", json={"source_ids": [s["id"]]}).json()
    run_id = cr["id"]
    r = client.get(f"/collect-runs/{run_id}", headers={"X-Workspace-Id": "2"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "collect_run_not_found"


def test_get_invite_run_other_workspace_returns_404(client, fake_tg):
    t = client.post("/targets", json={"identifier": "@iso_tgt", "enabled": True}).json()
    ir = client.post(
        "/invite-runs",
        json={"target_id": t["id"], "policy": {"max_per_minute": 2, "max_per_hour": 30, "cooldown_minutes": 0}},
    ).json()
    run_id = ir["id"]
    r = client.get(f"/invite-runs/{run_id}", headers={"X-Workspace-Id": "2"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "invite_run_not_found"
