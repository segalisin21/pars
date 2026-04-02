"""Regression: data is isolated by X-Workspace-Id."""

from __future__ import annotations


def test_sources_isolated_by_workspace_header(client):
    r1 = client.post("/sources", headers={"X-Workspace-Id": "1"}, json={"type": "group", "identifier": "@w1", "enabled": True})
    assert r1.status_code == 201, r1.text
    r2 = client.post("/sources", headers={"X-Workspace-Id": "2"}, json={"type": "group", "identifier": "@w2", "enabled": True})
    assert r2.status_code == 201, r2.text

    only1 = client.get("/sources", headers={"X-Workspace-Id": "1"}).json()["items"]
    only2 = client.get("/sources", headers={"X-Workspace-Id": "2"}).json()["items"]
    ids1 = {x["identifier"] for x in only1}
    ids2 = {x["identifier"] for x in only2}
    assert "w1" in ids1 and "w2" not in ids1
    assert "w2" in ids2 and "w1" not in ids2
